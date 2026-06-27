# 文档发布

OpenTalking 使用 MkDocs 和 Material for MkDocs 构建文档站，并用 `mike` 维护版本化发布目录。

## 本地验证

安装文档依赖：

```bash
python -m pip install -r docs/requirements.txt
```

按 CI 口径构建：

```bash
python -m mkdocs build --strict --clean
```

## 版本化发布

`main` 分支 push 会默认发布一个入口：

- `/latest/`：当前 main 分支文档，也是站点默认入口

正式版本发布时，从对应 release 分支或 tag 手动触发 `.github/workflows/docs-pages.yml`，把 `version` 设为发布号，例如 `v0.1.0`。正式版本会保留在 `/v0.1.0/` 这样的冻结路径下，不会被后续 main 文档覆盖。如果希望站点根路径默认进入某个版本，把 `default_version` 设为对应版本或 `latest`。

workflow 会先把版本化站点内容写入 `gh-pages` 分支。如果仓库尚未启用 GitHub Pages，它仍会维护 `gh-pages` 内容，但会跳过 Pages artifact 和 deploy 步骤。启用 Pages 时，source 选择 GitHub Actions。
