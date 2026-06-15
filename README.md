# 选股

这是从 InStock 中独立拆出的单机网页项目，不依赖数据库或原 InStock 服务。

## 功能

- 从公开网络数据源获取实时行情和复权日 K 数据
- 展示基本信息、K 线、均线、成交量和 MACD 图表
- 分析均线、MACD、当日 K 线、RSI、成交量并给出综合结论

## 启动

直接双击 `启动选股.bat`，然后打开：

<http://localhost:9990/>

如需在其他环境安装：

```powershell
pip install -r requirements.txt
python app.py
```

行情可能存在延迟，分析结果不构成投资建议。
