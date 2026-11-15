# Agent 辅助核验与校谱

`music-translator` 是本地 stdio MCP 服务。一次调用读取一页原谱并返回 PNG、该页 MusicXML 摘录和原位报告中的对齐、超时值、延音疑点。服务只读，模型与账号由 Agent 客户端管理。页图和摘录进入 Agent 会话，数据处理方式取决于客户端和所用模型。

## 接入支持 MCP 的 Agent 工具

安装好[项目运行环境](macos_setup.md)后，在仓库根目录安装 MCP SDK：

```bash
source scripts/env.sh
python -m pip install 'mcp==1.30.0'
```

通过 uv 管理环境时，也可用 `uv pip install --python "$(command -v python)" 'mcp==1.30.0'`。在客户端添加本地 stdio MCP 服务，命令设为 `/bin/bash`，参数为启动脚本的绝对路径。客户端使用 `mcpServers` JSON 配置时，可参考下面的示例：

```json
{
  "mcpServers": {
    "music-translator": {
      "command": "/bin/bash",
      "args": ["/absolute/path/music-translator-macos/scripts/run_score_review_mcp.sh"]
    }
  }
}
```

客户端需要能启动本机进程、访问指定文件，并把工具返回的 MCP 图像和文本交给支持视觉输入的模型。启动脚本的诊断信息写到 stderr，stdout 用于 MCP 协议。

启用服务后，在客户端的工具列表中确认已有 `review_score_page`。用 Mac 应用转换单份 PDF 后，点「复制校谱提示」并粘贴到 Agent 会话。已有转换产物时，可直接在会话中提供文件路径和页码。

## 按页核验和确认修订

1. 先转换源 PDF，保留源调 MusicXML 与原位逐行报告 `*.insitu.report.json`。已有这些文件时可直接校对。
2. 调用 `review_score_page`。参数 `page` 是从 1 开始的**原 PDF**页码。可只传 `report_path` 让服务定位文件，或同时传 `pdf_path`、`musicxml_path`。工具参数使用本机绝对路径。叠加原位报告时，工具核查报告记录的两份源文件哈希。旧报告若使用无法解析的相对路径，可另外指定这两份源文件。移调后请显式提供原谱与源调 MusicXML。
3. 让 Agent 先核对告警集中页，逐项给出原谱页码、谱行、印刷小节编号或页内位置、MusicXML 小节索引、原图依据和建议修正。遇到多小节休止时两种小节编号可能不同。页码映射优先用 MusicXML 分页，缺失时按 PDF 谱表与小节数推定。
4. 确认差异后，在新的 MusicXML 副本修改。用 `python jianpu.py 原谱.pdf --mxl 校对版.musicxml --mode both --strict -o 校对版` 重导两种简谱。检查新报告的 `alignment_mismatch_count`、`overfilled_measure_count`、`rendered_staff_count`，再对照修订后的谱面。整谱逐音准确率需要另行核验。

可直接使用这段提示：

> 请调用 music-translator 的 review_score_page 核对这份分谱的原 PDF 第 2 页。原位报告在「替换成 .insitu.report.json 的绝对路径」。请对照原图和 MusicXML，优先核查小节对齐、时值、休止和连音。用原页码、谱行和 MusicXML 索引定位，写明图像依据和拟修改内容。证据不充分的标为待核对。

目前支持只有一个 MusicXML part 的分谱。MCP 返回证据由 Agent 判断，小节对齐或图像辨识仍可能存在误差。
