# onlyoffice 阅读器（外部引擎）

| 项 | 内容 |
|---|---|
| 来源 | [ONLYOFFICE Docs](https://github.com/ONLYOFFICE/DocumentServer) 的浏览器接口 `web-apps/apps/api/documents/api.js`，由引擎自己提供，不打包进 burrowl |
| 版本 | 按 ONLYOFFICE Docs 8.x 的接口编写（`DocsAPI.DocEditor`、`documentType` 含 `pdf`） |
| 许可证 | 引擎是 AGPL-3.0，作为用户自己运行的独立服务通过网络使用；本目录只有调用它的几十行代码 |
| 显示的格式 | Word、Excel、PPT、PDF（引擎原生排版，还原度最高） |
| 能力 | 分页；只读查看（`mode=view`，不能编辑、批注、审阅）；引擎自带缩放、查找、目录 |
| 改动 | 无 |
| 已知限制 | 社区版在只读模式下没有往文档里加批注的接口（Automation API 属于开发者版），段落标注只在阅读模式侧栏里列出；引擎要能访问工作台取文件：引擎在 Docker 里时，在设置里把"引擎访问 burrowl 的地址"填成 `http://host.docker.internal:端口`；引擎开着 JWT 时把同一个密钥填进设置 |

## 安装引擎（用户自己做）

```
docker run -d -p 8080:80 -e JWT_SECRET=<自己定的密钥> onlyoffice/documentserver
```

然后在工作台"设置 → 阅读"里填写：ONLYOFFICE 地址 `http://127.0.0.1:8080`、JWT 密钥、引擎访问 burrowl 的地址，点"测试连接"，再把 Word / Excel / PPT 的默认阅读器换成"ONLYOFFICE（外部）"。
