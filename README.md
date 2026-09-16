# campus-login — 校园网自动登录（Selenium + Edge）

> py: miaoxiawa

针对锐捷 SAM 门户（Angular + Ionic，表单藏在 iframe + Shadow DOM 里）的 Python 自动登录脚本，
在 Windows 11 + Edge 环境实测通过。

## 功能

- **自动登录**：打开认证页 → 自动切 iframe → 填账号密码 → 勾协议 → 点登录
- **运营商选择**：登录后弹「请选择服务」时，按 `config.ini` 自动选；首次运行在控制台选一次即自动保存
- **仅下线**：点「我要下线」断开校园网，不重连
- **断线重连**：下线 → 等 10 秒 → 自动重新登录（一键自测整条链路）
- **安全停手**：识别「密码错误/账号不存在/已锁定」等关键词立即退出，防止反复重试锁号
- **全程留痕**：日志、截图、页面源码、`RESULT.txt` 结果报告全部落盘 `logs/`

## 使用

1. 首次运行会自动用 `config.example.ini` 生成 `config.ini`（认证页地址已内置），只需按提示输入学号密码；也可手动复制模板填写
2. 双击 `登录一次.bat` 登录；双击 `仅下线.bat` 断网；双击 `侦查页面.bat` 查看页面结构
3. 双击 `安装开机自启.bat` 可注册开机自动登录（写入启动文件夹，无需管理员权限）

## 依赖

- Python 3.10+，`pip install selenium`（Selenium Manager 自动管理 EdgeDriver）
- Windows + Microsoft Edge
