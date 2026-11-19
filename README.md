# Notice Desk

内部通知制作与审批网页应用。适用于 Inndeavor Leasing Pty Ltd 的 RTA 和 A&R Co-living Pty Ltd 的 OA，每个主体支持涨价、违约整改和终止三类通知。

## 本机运行

需要 Python 3.11 或更新版本。在本目录执行以下命令，再打开 [Notice Desk](http://127.0.0.1:8770)。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app add-user
flask --app app add-user
flask --app app run --host 127.0.0.1 --port 8770
```

创建账号时分别选 `junior` 和 `cm`。CM 电话为必填项。密码至少 12 个字符。账号管理通过命令行操作。

## 审批与下载

- Junior CM 选择主体和通知类型，填写草稿、选指定 CM。系统自动带出 CM 电话，签发或送达日期默认悉尼当地当天并可修改。签发或送达当天为第 0 天。RTA 涨租自动计算 60 天，OA 涨费自动计算 28 天，RTA 整改期限手动填写，RTA 终止根据理由和适用的协议条件计算。邮寄时另填用于起算的送达日期。保存后可打开带草稿标识的 PDF 预览。
- CM 审核后可填意见退回，或在签名区手写签名并点击 Confirm。系统记录签字和确认时间，并锁定正式 PDF。
- RTA 整改和 RTA 终止的协议违约分支提供合同条款预设。吸烟、阳台晾晒等选择要求填写适用的大楼规则或附加条款编号及全文。RTA 整改通知将所选条款全文填入正文的条款框。RTA 终止的违约分支将所选条款全文附于 PDF 后。
- 已确认的 RTA 终止通知提供独立的 Termination Information Statement 下载，并提示发出通知时一并附上。其他证明材料由 CM 按理由核对，成员负责实际送达。
- 已确认通知可创建修订草稿。原件和历次提交、退回与确认记录保存在数据库里。

## RTA 终止模板来源

系统使用 NSW Fair Trading 下载页标记为 2026 年 7 月 3 日更新的文件。PDF 页脚保留原表印刷日期 2025 年 6 月 20 日。源文件的 SHA-256 为 `acf3ca78334e462ac6574ca8a620edec7b8d4fb3c4de9cfad518d86f49d43b84`。 [NSW Fair Trading 下载页](https://www.nsw.gov.au/housing-and-construction/rental-forms-surveys-and-data/resources/notice-to-terminate-tenancy-agreement-by-landlord-or-agent)

## 运行配置

默认 SQLite 文件为 `notice.sqlite3`。多人部署时通过 `NOTICE_DB` 指定持久化路径，通过 `NOTICE_SECRET` 设置固定随机密钥，并在 HTTPS 下设置 `NOTICE_HTTPS=1`。生产部署使用 WSGI 服务器和 HTTPS 反向代理。数据库包含联系人、通知记录和已签文件，应限制访问并定期备份。

正式域名为 [notice.inndeavor.com](https://notice.inndeavor.com)。GitHub 上传、阿里云 ECS 原生部署、HTTPS、更新与备份详见 [部署指南](DEPLOY.zh-CN.md)。
