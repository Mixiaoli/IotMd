# IotMd
文档自动化生成项目解决运维文档滞后问题，开发基于 Markdown 和 Git 的文档管理系统。通过脚本自动抓取设备配置、网络拓扑等信息生成运维文档，实现“代码即文档”和 AI 识别生成文档的闭环管理。

## 项目目标
- 以 Markdown 为载体沉淀运维知识，保证文档可追溯、可协作。
- 以 Git 管理文档生命周期，形成变更留痕与审核流程。
- 以脚本自动化采集设备信息，降低人工维护成本。
- 通过 AI 识别生成内容，提升文档生成与检索效率。

## 适用设备
- 华为交换机
- 锐捷 AP

## 主要能力
- 自动抓取设备配置、接口状态、网络拓扑等信息。
- 基于模板渲染 Markdown 文档，保证格式一致性。
- 文档变更通过 Git 版本控制，便于回溯与审计。
- 支持将采集结果作为 AI 文档生成的结构化输入。

## 典型流程
1. 运行采集脚本获取设备配置与拓扑数据。
2. 将采集结果整理为标准化数据结构。
3. 渲染生成 Markdown 运维文档并提交至 Git。
4. 触发 AI 识别生成或补全说明内容，形成最终文档。

## 快速开始
1. 准备设备快照数据（示例见 `data/sample_snapshots/`）。

`data/sample_snapshots/` 目录内每个 JSON 文件代表一台设备的采集快照，你需要按实际环境修改以下字段：

- `name`：设备名称（用于拓扑节点识别）。
- `vendor` / `model` / `role`：厂商、型号与角色描述。
- `management_ip`：设备管理地址。
- `interfaces`：接口信息列表，包含接口名称、状态、VLAN 与描述。
- `config_snippet`：关键配置片段（可选，用于文档展示）。
- `neighbors`：邻居设备信息，用于生成链路拓扑，需要填写 `device`、`local_interface`、`remote_interface`、`medium`、`note`。

2. 运行扫描脚本生成拓扑数据：

```bash
python3 src/scan_network_topology.py \
  --input-dir data/sample_snapshots \
  --output data/generated_topology.json \
  --company "示例科技有限公司" \
  --region "总部机房"
```

3. 运行文档生成脚本（可选启用 AI 摘要）：

```bash
python3 src/generate_topology_doc.py \
  --input data/generated_topology.json \
  --output output/network_topology.md \
  --ai-summary
```

4. 在 `output/network_topology.md` 查看生成的公司网络拓扑文档。

## AI 接入说明
脚本支持对接 OpenAI 兼容接口生成摘要，请配置环境变量或传参：

- `AI_ENDPOINT`：OpenAI 兼容接口地址（例如 `https://api.openai.com/v1/chat/completions`）
- `AI_MODEL`：模型名称

也可在命令行中指定：

```bash
python3 src/generate_topology_doc.py \
  --input data/generated_topology.json \
  --output output/network_topology.md \
  --ai-summary \
  --ai-endpoint "https://api.openai.com/v1/chat/completions" \
  --ai-model "gpt-4o-mini"
```
