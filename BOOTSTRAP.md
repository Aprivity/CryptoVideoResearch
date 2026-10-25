# Ubuntu 一键部署（实验功能分支）

本安装器适用于全新 Ubuntu 22.04 / 24.04 / 26.04（x86_64 或 aarch64）。需要网络、sudo/root 权限和 curl；安装完成后在终端安全输入 DeepSeek API Key。不会自动登录 YouTube，也不会创建后台定时任务或进行交易。

## 只需执行一条命令

~~~bash
bash -c 'set -o pipefail; curl -fsSL https://raw.githubusercontent.com/Aprivity/CryptoVideoResearch/0554f7d98ba0a2a3688083b08d6f5869921bc907/scripts/bootstrap.sh | bash'
~~~

建议先阅读 [安装脚本](scripts/bootstrap.sh) 了解会安装什么内容；脚本下载地址固定到已验证兼容 Ubuntu 26.04 的提交，避免分支路径上的旧缓存；脚本运行时仍会检出最新的 V0.5 一键视频报告功能分支。

如果系统没有 curl，先运行：

~~~bash
sudo apt-get update && sudo apt-get install -y curl
~~~

## 自动安装内容

1. Ubuntu 系统依赖：git、curl、Python 3、pipx、xz-utils 等（需要 sudo）。
2. 若未安装 Node.js 24+，从 Node.js 官方下载 v24 安装包、验证 SHA-256 后放到用户目录。
3. 安装用户级 npm 包 @steipete/summarize@0.25.3，避免覆盖系统 npm 包。
4. 安装 yt-dlp[default] + EJS，以及可选的 secretstorage，**不安装 PyTorch / CUDA**。
5. 克隆指定功能分支到 ~/CryptoVideoResearch，创建 Python 虚拟环境，安装命令行程序。
6. 在终端隐藏输入 DeepSeek API Key（已有密钥不覆盖），运行 doctor 自检，再自动搜索 YouTube 市场新闻解读视频并默认调用 DeepSeek 生成最多两份独立报告。

密钥保存到 ~/.config/cryptovideoresearch/deepseek.key（0600 权限），绝不作为命令行参数。已存在的工作目录只在相同分支、没有未提交跟踪文件修改的情况下执行快进更新。

## 以后无需重新安装

在新终端执行，或者先 source ~/.profile：

~~~bash
cryptovideo run
cat ~/CryptoVideoResearch/outputs/youtube-news/latest.md
cryptovideo doctor

# 可选视频分析：桌面 Chrome 已登录时才使用 cookies。
cryptovideo analyze 'https://www.youtube.com/watch?v=ZWrgUWKOq_0' --cookies chrome
~~~

首次一键安装结束后自动尝试生成最多两份独立视频报告，可能消耗 DeepSeek API 额度；后续用 cryptovideo run。若只想免费检索候选，改用 cryptovideo youtube-news。

## Ubuntu 代理（可选）

如果网络依赖本地 HTTP/Mixed 代理，根据自己的端口配置：

~~~bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
unset ALL_PROXY all_proxy
~~~

脚本不猜测一个 SOCKS 代理端口是否同时支持 HTTP；非标准 socks:// 会临时转换为 socks5h://，但个别 HTTP 库仍可能需要自行设置 HTTP/Mixed 代理。

## 离线测试

~~~bash
cd ~/CryptoVideoResearch
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m cryptovideoresearch.news_monitor --fixture tests/fixtures/news_sample.xml --hours 100000
~~~

如果 YouTube 搜索全部失败，会保留旧报告，不代表安装整体失败。当前仅执行一次 YouTube 搜索及逐视频分析，不会自动启动周期任务或浏览器，无交易或投资建议功能。

## 下载 ZIP 后只运行一条命令

直接解压源码后执行 `bash run.sh`，首次运行会自动补装依赖并生成报告；详细用法见 [QUICKSTART.md](QUICKSTART.md)。
