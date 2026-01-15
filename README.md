# IotMd

文档自动化生成项目解决运维文档滞后问题，开发基于 Markdown 和 Git 的文档管理系统。

## 功能概览

- 支持华为交换机与锐捷 AP 设备配置与 LLDP 信息采集。
- 自动生成 Markdown 文档，包含总览、拓扑图（Mermaid）与设备详情。
- 可选启用 AI 总结，输出更易读的设备角色描述，并在交互模式中由 AI 生成更自然的问题。
- 支持自然语言查询与诊断，提供排查建议与优化思路。

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

如果希望启动后直接交互输入设备信息（IP/账号/密码），并由 AI 提示提问，请使用：

```bash
python -m iotmd --interactive --output output
```

交互模式启动后会提供选项：

1. 生成交换机文档（输出文档如下）
   - 网络拓扑图（自动更新）
   - IP 地址分配表
   - 设备清单（含序列号、维保信息占位）
   - 配置备份文档
   - 网络设计文档
2. 自然语言查询/诊断（持续对话）
3. 退出

## 常见问题

- 命令执行后没有任何输出？
  - 请确认设备网络可达、账号密码正确。
  - 尝试加上超时与继续执行参数，例如：
    ```bash
    python -m iotmd --inventory examples/inventory.yaml --output output --timeout 10 --continue-on-error
    ```
  - 如果设备启用了分页输出，请确保未关闭 SSH 交互提示。
  - 交互模式下若认证失败，会提示重新输入账号密码。
- AI 调用失败或提示代理错误？
  - 请检查网络代理/SSL 配置，确保能访问 `dashscope.aliyuncs.com`。
  - 如无法访问，将自动回退到非 AI 回答与摘要。

## 目录结构

- `iotmd/` 核心代码
- `examples/` 配置示例
- `output/` 生成的文档输出目录
  - `overview.md` 总览
  - `topology.md` 网络拓扑图
  - `ip_allocation.md` IP 地址分配表
  - `device_inventory.md` 设备清单
  - `config_backup.md` 配置备份文档
  - `network_design.md` 网络设计文档
  - `devices.md` 设备详细信息

## AI 总结

默认关闭。若需要启用，请在 `inventory.yaml` 中设置：

```yaml
ai:
  enabled: true
  api_base: "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
  model: "qwen-turbo"
  api_key: ""
```

支持环境变量 `DASHSCOPE_API_KEY`，或在交互模式中输入 API Key。
