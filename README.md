# IotMd

文档自动化生成项目解决运维文档滞后问题，开发基于 Markdown 和 Git 的文档管理系统。

## 功能概览

- 支持华为交换机与锐捷 AP 设备配置与 LLDP 信息采集。
- 自动生成 Markdown 文档，包含总览、拓扑图（Mermaid）与设备详情。
- 可选启用 AI 总结，输出更易读的设备角色描述。

## 快速开始

1. 安装依赖并安装 CLI

```bash
pip install -r requirements.txt
pip install -e .
```

2. 准备设备清单（示例在 `examples/inventory.yaml`）

3. 生成文档

```bash
iotmd --inventory examples/inventory.yaml --output output
```

如果没有安装 CLI，也可以直接运行：

```bash
python -m iotmd --inventory examples/inventory.yaml --output output
```

如果希望启动后直接交互输入设备信息（IP/账号/密码），请使用：

```bash
python -m iotmd --interactive --output output
```

## 常见问题

- 命令执行后没有任何输出？
  - 请确认设备网络可达、账号密码正确。
  - 尝试加上超时与继续执行参数，例如：
    ```bash
    python -m iotmd --inventory examples/inventory.yaml --output output --timeout 10 --continue-on-error
    ```
  - 如果设备启用了分页输出，请确保未关闭 SSH 交互提示。

## 目录结构

- `iotmd/` 核心代码
- `examples/` 配置示例
- `output/` 生成的文档输出目录

## AI 总结

默认关闭。若需要启用，请在 `inventory.yaml` 中设置：

```yaml
ai:
  enabled: true
  api_base: "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
  model: "qwen-turbo"
```

并设置环境变量 `DASHSCOPE_API_KEY`。
