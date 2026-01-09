# IotMd

文档自动化生成项目解决运维文档滞后问题，开发基于 Markdown 和 Git 的文档管理系统。

## 功能概览

- 支持华为交换机与锐捷 AP 设备配置与 LLDP 信息采集。
- 自动生成 Markdown 文档，包含总览、拓扑图（Mermaid）与设备详情。
- 可选启用 AI 总结，输出更易读的设备角色描述。

## 快速开始

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 准备设备清单（示例在 `examples/inventory.yaml`）

3. 生成文档

```bash
iotmd --inventory examples/inventory.yaml --output output
```

## 目录结构

- `iotmd/` 核心代码
- `examples/` 配置示例
- `output/` 生成的文档输出目录

## AI 总结

默认关闭。若需要启用，请在 `inventory.yaml` 中设置：

```yaml
ai:
  enabled: true
  api_base: "https://api.openai.com/v1"
  model: "gpt-4o-mini"
```

并设置环境变量 `OPENAI_API_KEY`。
