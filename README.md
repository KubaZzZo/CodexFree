# CodexFree - ChatGPT 自动注册工具

一个用于自动化 ChatGPT 账号注册的 Python 工具，支持批量注册、代理配置和 Cloudflare 绕过。

## 功能特性

- 🤖 **自动化注册**: 完全自动化的 ChatGPT 账号注册流程
- 🔄 **批量处理**: 支持一次性注册多个账号
- 🌐 **代理支持**: 内置代理配置，支持 HTTP/HTTPS/SOCKS5 代理
- 🛡️ **Cloudflare 绕过**: 使用 Playwright + Stealth 插件绕过 Cloudflare 验证
- 📱 **短信转发**: 可选的短信验证码转发功能（Bark）
- 💾 **结果保存**: 自动保存成功和失败的注册记录
- 🎯 **Sentinel 令牌**: 自动提取和缓存 Cloudflare Sentinel 令牌

## 系统要求

- Python 3.8+
- Playwright 浏览器驱动
- Windows/Linux/macOS

## 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/KubaZzZo/CodexFree.git
cd CodexFree
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 安装 Playwright 浏览器

```bash
playwright install chromium
```

### 4. 配置文件

复制示例配置文件并编辑：

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
    "phone_number": "+86 138 0000 0000",
    "proxy": {
        "default": "http://username:password@proxy.example.com:8080"
    },
    "sms_forward": {
        "enabled": false,
        "bark_url": ""
    },
    "headless": false,
    "auto_confirm_sms": false
}
```

## 使用方法

### 基本命令

#### 注册单个账号

```bash
python main.py register
```

#### 批量注册

```bash
python main.py register --count 5
```

#### 登录已有账号

```bash
python main.py login
```

#### 注册并登录

```bash
python main.py all --count 3
```

### 命令行参数

- `register`: 注册新账号
- `login`: 登录已有账号
- `all`: 注册并登录
- `--count N`: 批量处理数量（默认为 1）

## 项目结构

```
CodexFree/
├── main.py                 # 主程序入口
├── chatgpt_register.py     # ChatGPT 注册逻辑
├── codex_login.py          # Codex 登录逻辑
├── sentinel.py             # Sentinel 令牌提取
├── email_api.py            # 邮箱 API 接口
├── register_gui.py         # GUI 界面（可选）
├── config.json             # 配置文件（需自行创建）
├── config.example.json     # 配置文件示例
├── requirements.txt        # Python 依赖
├── .gitignore             # Git 忽略规则
└── README.md              # 项目说明
```

## 配置说明

### 基础配置

- **phone_number**: 用于注册的手机号码（国际格式）
- **headless**: 是否使用无头模式运行浏览器（true/false）
- **auto_confirm_sms**: 是否自动确认短信验证码（true/false）

### 代理配置

支持多种代理格式：

```json
{
    "proxy": {
        "default": "http://username:password@proxy.example.com:8080"
    }
}
```

代理格式示例：
- HTTP: `http://user:pass@host:port`
- HTTPS: `https://user:pass@host:port`
- SOCKS5: `socks5://user:pass@host:port`

### 短信转发配置

如果需要将验证码转发到手机：

```json
{
    "sms_forward": {
        "enabled": true,
        "bark_url": "https://api.day.app/your_key/"
    }
}
```

## 高级功能

### Sentinel 令牌缓存

工具会自动提取并缓存 Cloudflare Sentinel 令牌到 `sentinel_cache.json`，避免重复提取。缓存有效期为 24 小时。

### 结果保存

- 成功的注册记录保存在 `success/` 目录
- 失败的记录保存在 `fail/` 目录
- 每条记录包含时间戳和详细信息

### 代理会话管理

对于支持会话的代理服务（如 1024proxy），工具会自动管理会话 ID：

```python
# 会话格式示例
username-region-Rand-sid-{random_id}-t-{minutes}:password
```

## 故障排除

### 常见问题

#### 1. Playwright 浏览器未安装

```bash
playwright install chromium
```

#### 2. 代理连接失败

- 检查代理地址和端口是否正确
- 确认代理服务器是否在线
- 验证用户名和密码是否正确
- 检查代理服务器的 IP 白名单设置

#### 3. Cloudflare 验证失败

- 确保已安装 `playwright-stealth`
- 尝试降低请求频率
- 检查代理 IP 是否被封禁

#### 4. 短信验证码接收失败

- 确认手机号格式正确（国际格式）
- 检查短信转发配置
- 验证 Bark URL 是否有效

### 调试模式

设置 `headless: false` 可以看到浏览器操作过程，便于调试：

```json
{
    "headless": false
}
```

## 安全注意事项

⚠️ **重要提示**：

1. **不要将 `config.json` 提交到 Git 仓库**
2. **不要分享包含真实凭据的配置文件**
3. **定期更换代理密码**
4. **使用强密码保护账号**
5. **遵守 OpenAI 服务条款**

`.gitignore` 已配置忽略敏感文件：
- `config.json`
- `sentinel_cache.json`
- `success/` 和 `fail/` 目录
- `tokens/` 目录

## 依赖项

主要依赖包：

- `playwright>=1.40.0` - 浏览器自动化
- `playwright-stealth>=1.0.0` - Cloudflare 绕过
- `requests>=2.31.0` - HTTP 请求
- `curl-cffi>=0.5.0` - cURL 模拟
- `PySocks>=1.7.1` - SOCKS 代理支持

完整依赖列表见 `requirements.txt`。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 许可证

本项目仅供学习和研究使用。使用本工具时请遵守相关法律法规和服务条款。

## 免责声明

本工具仅用于技术研究和学习目的。使用者需自行承担使用本工具的一切风险和责任。作者不对因使用本工具而产生的任何直接或间接损失负责。

## 联系方式

- GitHub: [@KubaZzZo](https://github.com/KubaZzZo)
- 项目地址: [https://github.com/KubaZzZo/CodexFree](https://github.com/KubaZzZo/CodexFree)

---

⭐ 如果这个项目对你有帮助，请给个 Star！
