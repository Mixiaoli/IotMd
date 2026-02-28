# IotMd

文档自动化生成项目解决运维文档滞后问题，开发基于 Markdown 和 Git 的文档管理系统。

## 功能概览

- 支持华为交换机与锐捷 AP 设备配置与 LLDP 信息采集。
- 自动生成 Markdown 文档，包含总览、拓扑图（Mermaid）、设备资产表（型号/SN/版本）与设备详情。
- 支持按网段扫描（Ping + SSH）设备（例如 `10.133.12.0/24`），输出完整网段清单（离线IP也保留为预留行）。
- 可选启用 AI 总结，输出更易读的设备角色描述，并在交互模式中由 AI 生成更自然的问题。
- 支持自然语言查询与诊断，提供排查建议与优化思路。

- 华为采集默认执行：`display current-configuration`、`display lldp neighbor brief`、`display interface brief`、`display version`。

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

如果希望启动后以 AI 助手身份交互，并由 AI 提示提问（默认开启 AI，总结与建议会自动生成），请使用：

```bash
python -m iotmd --interactive --output output
```

交互模式启动后会先询问是否要生成交换机文档，默认先进入对话模式，再按需加载设备信息。若已配置 `DASHSCOPE_API_KEY` 环境变量，将不会再提示输入。

交互模式会提供欢迎语与选项：

1. 自然语言查询/诊断（持续对话）
2. 生成交换机文档（输出文档如下）
   - 网络拓扑图（自动更新）
   - IP 地址分配表
   - 设备资产清单表（设备名称/厂商/型号/管理地址/管理方式/用户名/SN/软件版本/AI建议/备注）
   - 配置备份文档
   - 全网安全与网络优化建议
3. 退出

在自然语言对话中，你可以随时输入“生成文档”触发文档输出，或输入“加载设备”再补充设备信息。

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
  - `summary.md` 汇总文档（含拓扑、IP 表、设备清单、配置备份与建议）

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


## Web 页面（对话 + 文档下载）

启动命令：

```bash
python -m iotmd --web --host 127.0.0.1 --port 8765 --output output
```

打开浏览器访问 `http://127.0.0.1:8765`，可在页面内：

1. 上传 `inventory.yaml`（系统自动采集设备）
2. 在对话框中直接输入“生成文档”
3. AI 在对话消息里返回下载链接，直接下载 `summary.md`
