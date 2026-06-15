# 选股

这是从 InStock 中独立拆出的单机网页项目，不依赖数据库或原 InStock 服务。

## 功能

- 从公开网络数据源获取实时行情和复权日 K 数据
- 展示基本信息、K 线、均线、成交量和 MACD 图表
- 分析均线、MACD、当日 K 线、RSI、成交量并给出综合结论

## 本地启动

直接双击 `启动选股.bat`，然后打开：

<http://localhost:9990/>

如需在其他环境安装：

```powershell
pip install -r requirements.txt
python app.py
```

## 部署为独立网页

本项目是需要运行 Python 的动态网站，不能直接使用 GitHub Pages。仓库已包含 `render.yaml`，可以部署到 Render：

1. 登录 <https://render.com/>，使用 GitHub 账户授权。
2. 选择 `New` → `Blueprint`。
3. 连接 `xiayuqileo-spec/Stock-Selection` 仓库。
4. 确认创建 `stock-selection` Web Service。
5. 部署完成后，Render 会提供一个公开网址。

每次向 `main` 分支推送修改后，Render 会自动重新部署。

可以通过查询参数直接分享指定股票分析，例如：

```text
https://你的服务地址.onrender.com/?code=600519
```

行情可能存在延迟，分析结果不构成投资建议。
