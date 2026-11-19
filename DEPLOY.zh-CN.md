# Notice Desk 上传与部署指南

正式入口为 **https://notice.inndeavor.com**。这套流程适用于 **阿里云 ECS、Ubuntu 24.04 LTS、普通 SSH 管理员账号**。应用以 Python 虚拟环境运行，由 systemd 管理，前面接 Nginx。员工通过浏览器制作、审核和下载通知，使用自己的 Notice Desk 账号登录。实际送达仍由员工负责。

| 内容 | 位置 |
|---|---|
| GitHub 仓库 | 私有仓库 `notice-desk` |
| 云端源码 | `/opt/notice-desk` |
| 应用服务 | `notice-desk.service` |
| 环境配置 | `/etc/notice-desk.env` |
| 账号、通知、签字 PDF 和审批记录 | `/var/lib/notice-desk/notice.sqlite3` |
| 反向代理上游 | `http://127.0.0.1:8770` |

## 1. 在 Mac 解压并上传至 GitHub

1. 下载 ZIP，双击解压，打开 `notice-desk-source` 文件夹。在 Finder 按 **⌘ + Shift + .** 可看到 `.gitignore` 和 `.env.example`。包内是程序、PDF 模板和部署配置。正式账号在云端新建。
2. 登录 GitHub，点右上角 **+ → New repository**。选公司组织或指定账号为 **Owner**，仓库名填 `notice-desk`，可见性选 **Private**，勾选 **Add a README**，点 **Create repository**。
3. 进入仓库的 **Code** 页，点 **Add file → Upload files**。打开解压后的 `notice-desk-source`，把**里面的文件和文件夹**拖到上传区，保持 `deploy/`、`forms/`、`static/` 和 `templates/` 的目录结构。提交说明可填 `Add Notice Desk source and deployment files`，然后点 **Commit changes**。已有同名 README 时，提交后用包内的 README 覆盖原始占位内容。
4. 回到 **Code** 页面，确认仓库根目录直接看到 `app.py`、`pdf_forms.py`、`requirements.txt`、`DEPLOY.zh-CN.md` 和上述四个目录。确认 `.gitignore` 已上传，仓库显示 **Private**。上传清单里应只有源码、空白配置示例和模板。

如果浏览器上传遗漏隐藏文件或目录，可用 **GitHub Desktop** 打开该仓库。选择 **File → Clone Repository**，把解压目录里的内容复制进克隆目录，在 **Changes** 检查文件后，填写提交说明、点击 **Commit to main → Push origin**。使用一种上传方式即可。 [GitHub 上传文件](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)

## 2. 准备阿里云服务器和域名

1. 在阿里云 **ECS → 实例** 找到用于部署的实例，记录公网 IPv4 或绑定的 EIP 和 SSH 登录账号。可复用现有服务器。以下命令以 Ubuntu 24.04 为例，在服务器运行 `cat /etc/os-release` 可查看系统。服务器在中国内地时，公网网站上线前按阿里云对应流程办理 ICP 备案。 [阿里云 ECS 建站说明](https://www.alibabacloud.com/help/en/ecs/user-guide/build-a-website/)
2. 检查 ECS 入方向安全组。开放 TCP **80、443** 用于网站与证书，TCP **22** 仅允许管理员来源 IP。应用端口 **8770** 只绑定服务器自身的回环地址。服务器本身如有防火墙，也要允许网站端口。 [阿里云安全组说明](https://www.alibabacloud.com/help/en/ecs/user-guide/security-groups-for-different-use-cases)
3. 打开 `inndeavor.com` 当前实际使用的 DNS 管理平台，添加下表记录。修改前先检查是否已有同名记录，确认它的用途后再变更。 [阿里云添加 DNS 记录](https://www.alibabacloud.com/help/en/dns/pubz-add-parsing-record)

| DNS 字段 | 填写内容 |
|---|---|
| 记录类型 | A |
| 主机记录 | `notice` |
| 记录值 | ECS 公网 IPv4 或绑定的 EIP |
| TTL | 使用默认值 |

在 Mac 终端确认查询结果是对应公网 IP。使用 IPv4 部署时，如已存在指向别处的同名 AAAA 记录，需要先处理。

```sh
dig +short A notice.inndeavor.com
dig +short AAAA notice.inndeavor.com
```

## 3. 让 ECS 读取 GitHub 私有库

以下命令在 ECS 上运行。先从 Mac 的终端执行 `ssh 登录用户名@ECS公网IP`，也可使用阿里云 Workbench 登录。

```sh
sudo apt update
sudo apt install -y git python3 python3-venv openssl sqlite3 curl
python3 --version
sudo ss -ltnp
```

如果 8770 已用于其他软件，先选一个空闲本机端口，并在后面同步修改环境文件的 `NOTICE_BIND` 和反向代理上游。

生成专用于此仓库的 SSH 密钥。命令应在实际负责从 GitHub 拉取更新的普通账号下执行。

```sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/notice-desk-github -C notice-desk-ecs
cat ~/.ssh/notice-desk-github.pub
```

1. 复制屏幕显示的 **公钥**。在 GitHub 该私有仓库进入 **Settings → Deploy keys → Add deploy key**，Title 填 `Notice Desk ECS`，粘贴公钥，保持 **Allow write access** 未勾选，然后点 **Add key**。服务器上的私钥用于后续拉取。 [GitHub Deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
2. 替换命令中的 `YOUR_GITHUB_OWNER` 为 GitHub 中真实的账号或组织名称。如果仓库名自定义，也修改 URL。首次连接 GitHub 时，对照官方 SSH 指纹后接受主机密钥。 [GitHub SSH 公钥指纹](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)

```sh
sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" /opt/notice-desk
GIT_SSH_COMMAND="ssh -i $HOME/.ssh/notice-desk-github -o IdentitiesOnly=yes" \
  git clone git@github.com:YOUR_GITHUB_OWNER/notice-desk.git /opt/notice-desk
cd /opt/notice-desk
git config --local core.sshCommand "ssh -i $HOME/.ssh/notice-desk-github -o IdentitiesOnly=yes"
ls
```

预期能看到 `app.py` 和 `deploy/`。如果 `/opt/notice-desk` 已有文件，先检查它是否是原有部署目录，勿覆盖现有安装。

## 4. 安装应用并开机启动

以下为首次部署命令。从 `/opt/notice-desk` 执行。

```sh
cd /opt/notice-desk
python3 -m venv .venv
.venv/bin/python -m pip install -r deploy/requirements.txt

getent passwd notice-desk >/dev/null || \
  sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin notice-desk
```

首次生成正式环境配置使用下面这一段。如果服务器已存在生效中的 `/etc/notice-desk.env`，保留其中的密钥和数据路径。

```sh
sudo sh -c 'set -euC
umask 077
{
  notice_secret=$(openssl rand -hex 32)
  printf "NOTICE_SECRET=%s\n" "$notice_secret"
  printf "%s\n" \
    "NOTICE_DB=/var/lib/notice-desk/notice.sqlite3" \
    "NOTICE_HTTPS=1" \
    "NOTICE_BIND=127.0.0.1:8770"
} > /etc/notice-desk.env'
```

如果前面确认 8770 已占用，用 `sudoedit /etc/notice-desk.env` 把末行改为选定的回环端口。再安装并启动服务。

```sh
sudo install -m 0644 deploy/notice-desk.service /etc/systemd/system/notice-desk.service
sudo systemctl daemon-reload
sudo systemctl enable --now notice-desk
sudo systemctl status notice-desk --no-pager
curl -fsS http://127.0.0.1:8770/login -o /dev/null
```

`status` 应显示 **active (running)**。如已改端口，替换上述 `curl` 地址。首次启动时 systemd 建立持久化目录，应用初始化空数据库。

## 5. 创建正式账号

在 ECS 上分别执行下列命令一次，为每位员工创建独立账号。第一次选择 `junior`，测试 CM 的账号选择 `cm`。系统会提示用户名、全名和密码，CM 还需要填写会印在通知上的联系电话。密码至少 12 字符，执行时会隐藏输入。

```sh
cd /opt/notice-desk
sudo -u notice-desk env NOTICE_DB=/var/lib/notice-desk/notice.sqlite3 \
  /opt/notice-desk/.venv/bin/python -m flask --app app add-user
```

员工使用本系统账号登录；审批时 CM 在浏览器手写签名。

## 6. 接入 Nginx 和 HTTPS

**已有宝塔或其他面板的服务器**：用现有 Nginx 或面板添加一个独立站点，域名填 `notice.inndeavor.com`，上游填 `http://127.0.0.1:8770`，启用该域名的 SSL 证书和 HTTP 跳转 HTTPS。使用自己选定的应用端口，并保留已有站点配置。

**使用 Ubuntu 标准 Nginx 配置的服务器**：以下命令安装网站配置。如果机器已经运行其他 Web 服务，先确认 80 和 443 由哪个服务管理，再在已有服务中添加站点。

```sh
sudo apt install -y nginx
cd /opt/notice-desk
sudo install -m 0644 deploy/notice.inndeavor.com.conf /etc/nginx/sites-available/notice.inndeavor.com
sudo ln -s /etc/nginx/sites-available/notice.inndeavor.com /etc/nginx/sites-enabled/notice.inndeavor.com
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

如改过应用端口，用 `sudoedit /etc/nginx/sites-available/notice.inndeavor.com` 同步修改 `proxy_pass`，然后重新检查配置并 reload。等 DNS 生效且安全组已放行后配置证书。以下是 Ubuntu 通过 apt 安装 Certbot 的做法。如果服务器已有面板或其他 Certbot 安装方式，就用原方式签发和续期。

```sh
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx --redirect -d notice.inndeavor.com
sudo certbot renew --dry-run
```

登录使用 HTTPS。配置中启用了安全 Cookie。 [Certbot Nginx 官方说明](https://certbot.eff.org/instructions?os=snap&tab=standard&ws=nginx)

## 7. 上线验收

1. 从 Mac 浏览器打开 [正式登录页](https://notice.inndeavor.com/login)，检查证书、绿色双栏界面，以及账号能否登录。可用下面命令在未登录时检查样式返回状态。
2. 用虚拟资料逐套预览六个通知模板。确认 OA 主体为 **A&R Co-living Pty Ltd**，RTA 主体为 **Inndeavor Leasing Pty Ltd**。检查签发日、期限、条款和 CM 电话。
3. 用 Junior CM 提交一份测试通知，用 CM 退回，再用 Junior CM 修改后重新提交。CM 手写签名并确认，下载正式 PDF。再确认 RTA 终止通知可下载独立的 **Termination Information Statement**。
4. 重启应用服务后重新登录，检查测试记录和已确认 PDF 仍可下载。测试通过后再交给团队使用。

```sh
curl -I https://notice.inndeavor.com/login
curl -I https://notice.inndeavor.com/static/style.css
```

## 8. 日常更新

先将更新后的文件提交 GitHub 的 `main`。服务器只拉取源码、安装依赖并重启应用服务。正常代码更新沿用现有域名、Nginx、证书和数据库。

更新前先按第 9 节备份。在 ECS 的普通部署账号执行：

```sh
cd /opt/notice-desk
git status --short
git rev-parse HEAD
git pull --ff-only origin main
.venv/bin/python -m pip install -r deploy/requirements.txt
sudo systemctl restart notice-desk
sudo systemctl status notice-desk --no-pager
curl -fsS https://notice.inndeavor.com/login -o /dev/null
```

记下更新前的提交号。若代码需要回退，可在确认没有本地改动且新旧版本数据库兼容的前提下，运行 `git switch --detach 更新前的提交号`，重新安装该版本的依赖并重启服务。准备恢复正常更新时运行 `git switch main`。数据库恢复单独评估，以免覆盖更新后新增的记录。

## 9. 备份与排障

SQLite 在线备份会生成独立的完整副本，可在应用运行时执行。备份含真实租客数据和签署文件，存放在受限位置，并保留一份经加密的异地副本。环境文件和证书也应纳入服务器备份范围。

```sh
sudo install -d -m 0700 /var/backups/notice-desk
backup="/var/backups/notice-desk/notice-$(date +%Y%m%d-%H%M%S).sqlite3"
sudo sh -c 'umask 077; sqlite3 "$1" ".backup $2"' sh /var/lib/notice-desk/notice.sqlite3 "$backup"
sudo sqlite3 "$backup" 'PRAGMA integrity_check;'
```

正常返回 `ok`。如果需要从备份恢复，先安排维护窗口、停服务、另备份现有库，然后恢复到正式数据库路径，设置文件所有者 `notice-desk:notice-desk` 和权限 `0600`，启动后核对记录。

| 遇到的问题 | 先检查 |
|---|---|
| `git clone` 提示 `Permission denied (publickey)` | 确认 GitHub deploy key 已加到正确仓库，拉取时使用正确私钥和 Owner。 |
| HTTPS 证书签发失败 | 检查 DNS 解析到正确的 ECS 公网 IP，80、443 已放行，没有冲突的站点或错误的 AAAA 记录。 |
| 页面显示 502 | 检查应用是否启动、Nginx 上游端口是否与 `NOTICE_BIND` 一致。 |
| 样式缺失 | 检查 `/static/style.css` 返回 `200` 与 `Content-Type: text/css`，并核对 Nginx 是否把静态文件请求也交给应用。 |
| 登录后又回到登录页 | 使用正式 HTTPS 域名，确认 `NOTICE_SECRET` 固定，应用未反复重启。 |

```sh
sudo journalctl -u notice-desk -n 80 --no-pager
sudo nginx -t
sudo tail -n 60 /var/log/nginx/error.log
```
