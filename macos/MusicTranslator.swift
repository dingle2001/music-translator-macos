import AppKit
import SwiftUI
import UniformTypeIdentifiers

@main
struct MusicTranslatorApp: App {
    var body: some Scene {
        WindowGroup("五线谱转简谱") {
            ConverterView()
        }
        .windowResizability(.contentMinSize)
    }
}

@MainActor
final class ConversionState: ObservableObject {
    @Published var source: URL? = nil
    @Published var musicXML: URL? = nil
    @Published var output = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
    @Published var batch = false
    @Published var mode = "both"
    @Published var engine = "spaced"
    @Published var layout = "single"
    @Published var omr = "homr"
    @Published var backend = "auto"
    @Published var pitch = "movable"
    @Published var tonic = "C"
    @Published var strict = true
    @Published var zip = false
    @Published var midi = false
    @Published var editor = false
    @Published var transpose = ""
    @Published var melodyOnly = false
    @Published var running = false
    @Published var status = "请选择乐谱"
    @Published var log = ""
    @Published var logFile: URL? = nil
}

struct ConverterView: View {
    @StateObject private var model = ConversionState()

    private var pdf: Bool { model.batch || model.source?.pathExtension.lowercased() == "pdf" }
    private var audio: Bool {
        !model.batch && ["wav", "flac", "ogg", "mp3"].contains(model.source?.pathExtension.lowercased() ?? "")
    }
    private var proofreading: Bool {
        !model.batch && model.source?.lastPathComponent.lowercased().hasSuffix(".jianpu.txt") == true
    }
    private var needsOMR: Bool {
        model.batch || (model.musicXML == nil && ["pdf", "png", "jpg", "jpeg"].contains(model.source?.pathExtension.lowercased() ?? ""))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("五线谱转简谱").font(.title2.bold())
                    Text("在 Mac 上识谱、排版和导出").foregroundStyle(.secondary)
                }
                Spacer()
                Button("打开输出文件夹") { NSWorkspace.shared.open(model.output) }
            }
            Divider()
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Button("选择乐谱…") { chooseInput(directory: false) }
                    Button("选择批量目录…") { chooseInput(directory: true) }
                    Text(model.source?.lastPathComponent ?? "PDF、MusicXML、图片、MIDI 或钢琴音频")
                        .lineLimit(1).truncationMode(.middle).foregroundStyle(.secondary)
                    if proofreading, let source = model.source {
                        Button("编辑简谱文本") { NSWorkspace.shared.open(source) }
                    }
                    Spacer()
                }
                HStack {
                    Button("输出目录…") {
                        if let folder = select(directory: true) { model.output = folder }
                    }
                    Text(model.output.path).lineLimit(1).truncationMode(.middle).foregroundStyle(.secondary)
                    Spacer()
                }
                if pdf && !model.batch {
                    HStack {
                        Button("使用已有 MusicXML…") {
                            model.musicXML = select(types: ["musicxml", "xml", "mxl"])
                        }
                        if let musicXML = model.musicXML {
                            Text(musicXML.lastPathComponent).lineLimit(1)
                            Button("移除") { model.musicXML = nil }
                        } else {
                            Text("留空时运行乐谱识别").foregroundStyle(.secondary)
                        }
                    }
                }
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 10) {
                    GridRow {
                        Picker("导出", selection: $model.mode) {
                            Text("整页与原位").tag("both")
                            Text("整页简谱").tag("jianpu")
                            Text("原位对照").tag("insitu")
                        }.disabled(!pdf)
                        Picker("原位排版", selection: $model.engine) {
                            Text("同尺寸分页").tag("spaced")
                            Text("原位置叠印").tag("stamp")
                        }.disabled(!pdf || model.mode == "jianpu")
                        Picker("简谱行宽", selection: $model.layout) {
                            Text("一行对一行").tag("single")
                            Text("原字号换行").tag("wrap")
                        }.disabled(!pdf || model.mode == "jianpu")
                    }
                    GridRow {
                        Picker("识谱引擎", selection: $model.omr) {
                            Text("Homr").tag("homr")
                            Text("Audiveris").tag("audiveris")
                        }.disabled(!needsOMR)
                        Picker("Homr 后端", selection: $model.backend) {
                            Text("自动").tag("auto")
                            Text("CPU").tag("cpu")
                            Text("Core ML").tag("coreml")
                        }.disabled(!needsOMR || model.omr != "homr")
                        Picker("唱名", selection: $model.pitch) {
                            Text("首调").tag("movable")
                            Text("固定调").tag("fixed")
                        }.disabled(proofreading)
                    }
                }
                HStack(spacing: 15) {
                    if !proofreading && model.pitch == "fixed" {
                        TextField("固定调主音", text: $model.tonic).frame(width: 105)
                    }
                    if !model.batch && !proofreading {
                        TextField("移调目标，如 Bb", text: $model.transpose).frame(width: 128)
                    }
                    Toggle("严格检查", isOn: $model.strict)
                    if model.batch {
                        Toggle("打包原位谱 ZIP", isOn: $model.zip).disabled(model.mode == "jianpu")
                    } else if !proofreading {
                        Toggle("另存 MIDI", isOn: $model.midi).disabled(model.mode == "insitu")
                        Toggle("保存校对文本", isOn: $model.editor).disabled(model.mode == "insitu")
                        if audio { Toggle("仅主旋律", isOn: $model.melodyOnly) }
                    }
                }
            }
            .disabled(model.running)
            HStack {
                Button("开始转换", action: convert)
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.source == nil || model.running)
                if model.running { ProgressView().controlSize(.small) }
                Text(model.status).lineLimit(2)
                Spacer()
                if let logFile = model.logFile {
                    Button("打开完整日志") { NSWorkspace.shared.open(logFile) }
                }
            }
            ScrollView {
                Text(model.log.isEmpty ? "转换日志会显示在这里。" : model.log)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                    .padding(10)
            }
            .frame(minHeight: 145)
            .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
        }
        .padding(22)
        .frame(minWidth: 760, minHeight: 535)
    }

    private func select(directory: Bool = false, types: [String] = []) -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseFiles = !directory
        panel.canChooseDirectories = directory
        panel.canCreateDirectories = directory
        panel.allowedContentTypes = types.compactMap { UTType(filenameExtension: $0) }
        return panel.runModal() == .OK ? panel.url : nil
    }

    private func chooseInput(directory: Bool) {
        guard let selected = select(directory: directory,
                                    types: directory ? [] : ["pdf", "png", "jpg", "jpeg", "musicxml", "xml", "mxl",
                                                               "mid", "midi", "wav", "flac", "ogg", "mp3", "txt"]) else { return }
        model.source = selected
        model.batch = directory
        model.musicXML = nil
        model.mode = directory || selected.pathExtension.lowercased() == "pdf" ? "both" : "jianpu"
        model.status = "可以开始转换"
    }

    private func convert() {
        guard let source = model.source else { return }
        let fm = FileManager.default
        guard let config = Bundle.main.url(forResource: "repository", withExtension: "txt"),
              let path = try? String(contentsOf: config, encoding: .utf8) else {
            model.status = "无法读取工程目录，请重新构建应用。"
            return
        }
        let root = URL(fileURLWithPath: path.trimmingCharacters(in: .newlines), isDirectory: true)
        let stem = source.deletingPathExtension()
        let name = proofreading ? stem.deletingPathExtension().lastPathComponent : stem.lastPathComponent
        let cli = model.batch ? "batch.py" : "jianpu.py"
        var args = [cli, source.path, "--mode", model.mode, "--engine", model.engine,
                    "--layout", model.layout, "--pitch-mode", proofreading ? "movable" : model.pitch,
                    "--fixed-tonic", model.tonic,
                    "--omr", model.omr, "--backend", model.backend]
        if model.strict { args.append("--strict") }

        do {
            if model.batch {
                args += ["-o", model.output.path]
                if model.zip && model.mode != "jianpu" {
                    args += ["--zip", model.output.appendingPathComponent("原位简谱.zip").path]
                }
            } else {
                let target = model.output.appendingPathComponent(name)
                args += ["-o", target.path]
                if let musicXML = model.musicXML { args += ["--mxl", musicXML.path] }
                if !proofreading && model.midi && model.mode != "insitu" {
                    args += ["--midi", target.appendingPathExtension("mid").path]
                }
                if !proofreading && model.editor && model.mode != "insitu" {
                    args += ["--editor-workspace", model.output.appendingPathComponent("校对文件").path]
                }
                if audio && model.melodyOnly { args.append("--melody-only") }
                if !proofreading && !model.transpose.trimmingCharacters(in: .whitespaces).isEmpty {
                    args += ["--transpose-to", model.transpose]
                }
            }
            let path = model.output.appendingPathComponent(name + ".conversion.log")
            let hasReport = pdf && model.mode != "jianpu"
            guard fm.createFile(atPath: path.path, contents: nil) else {
                model.status = "无法写入日志，请选择可写的输出目录。"
                return
            }
            model.logFile = path
            let handle = try FileHandle(forWritingTo: path)
            let process = Process()
            process.currentDirectoryURL = root
            process.executableURL = URL(fileURLWithPath: "/bin/bash")
            process.arguments = ["-c", "source scripts/env.sh && exec python -u \"$@\"", "music-translator"] + args
            process.standardOutput = handle
            process.standardError = handle
            model.running = true
            model.status = "正在转换 " + source.lastPathComponent
            model.log = ""
            try process.run()
            try? handle.close()
            Task { @MainActor in
                while process.isRunning {
                    updateLog(path)
                    try? await Task.sleep(for: .milliseconds(350))
                }
                updateLog(path)
                model.running = false
                model.status = process.terminationStatus == 0
                    ? (hasReport ? "已生成。原位排版和识谱疑点见输出报告。" : "已生成简谱 PDF。")
                    : "转换未完成，请查看日志。"
            }
        } catch {
            model.running = false
            model.status = error.localizedDescription
        }
    }

    private func updateLog(_ path: URL) {
        guard let handle = try? FileHandle(forReadingFrom: path) else { return }
        defer { try? handle.close() }
        guard let size = try? handle.seekToEnd() else { return }
        try? handle.seek(toOffset: size > 24_000 ? size - 24_000 : 0)
        if let data = try? handle.readToEnd() {
            model.log = String(decoding: data, as: UTF8.self)
                .replacingOccurrences(of: "\r", with: "\n")
                .split(separator: "\n").suffix(28).joined(separator: "\n")
        }
    }
}
