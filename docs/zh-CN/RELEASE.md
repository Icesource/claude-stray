# 发布与版本管理

英文原版：[../RELEASE.md](../RELEASE.md)

如何在不打断"维护者本机正在用的 dashboard"的前提下,持续迭代。

## 为什么写这份文档

v0.5.0 之前所有改动直接落 `main`,意味着中间任何一次 commit 都可能
搞坏维护者**正在用**的 dashboard。本文档通过"在跑的 vs 在改的"分离
来解决这个问题。

## 分支模型

```
 main      ●──●──●──●──●──●──●──●     开发主干 (始终是 WIP)
            │            │     │
            │  topic    │  topic
            ●──●──●     │  ●──●──●
                  │     │        │
                  ▼     ▼        ▼
                合并/squash 回 main

 stable  ●──────────────●──────────●  维护者本机跑的版本
         ↑              ↑          ↑
         v0.5.0       v0.6.0    v0.7.0
         (tag)        (tag)     (tag)
```

| 分支              | 用途                                                              |
|-------------------|-------------------------------------------------------------------|
| `main`            | 开发主干。所有进行中的工作。两次 commit 之间可能短暂处于损坏状态。 |
| `stable`          | 维护者本机安装跑的版本。只在 release 时前进。                      |
| `topic` (`feat/...` / `fix/...` / `chore/...` / `docs/...`) | 每个特性的工作分支。从 `main` 切出,做完合回 `main`,合完即删。 |

**日常使用**跑 `stable`:

```bash
git checkout stable
python3 bin/serve.py     # 或者其它启动入口
```

**迭代**在 `main`(以及它的 topic 分支)上:

```bash
git checkout main
git pull
git switch -c feat/短名字
# ... 改 + 增量 commit (见 CONTRIBUTING.md) + 测试 ...
git switch main && git merge feat/短名字 && git branch -d feat/短名字
git push
```

`main` 已经稳到可以成为新"在跑的版本"时:

```bash
# 在 main 上,改完 + CHANGELOG 已加条目
git checkout stable
git merge --ff-only main          # 或者保留 merge commit
git tag -a vMAJOR.MINOR.PATCH -m "vMAJOR.MINOR.PATCH"
git push origin stable --tags
```

维护者本机:

```bash
git checkout stable && git pull
# 如果 serve.py 在跑,重启
```

## 版本号 — SemVer (0.x 阶段宽松)

`vMAJOR.MINOR.PATCH`,遵循 [Semantic Versioning](https://semver.org),
带 0.x 阶段的标准放宽:

| 升号   | 何时                                                                                        |
|--------|---------------------------------------------------------------------------------------------|
| MAJOR  | 用户可见契约的破坏性变更:cache schema 删字段、CLI 参数改名、hook 输出格式变了。 0.x 阶段 MINOR 也可以带破坏性(见下文 "0.x 规则")。 |
| MINOR  | 新功能、新 DD 落地、新派生 widget 等。                                                       |
| PATCH  | Bug 修复、文案微调、纯文档改动。                                                              |

**0.x 规则**: 在 < 1.0 阶段,MINOR 升号也可以带破坏性变更 — 我们还
没承诺向后兼容。给一个清晰的 CHANGELOG 条目就行。MAJOR (→ 1.0) 留
给"觉得外部用户可以放心依赖了"那一天。

**Tag 格式**: `vMAJOR.MINOR.PATCH`,固定 `v` 前缀。一律用 annotated
tag (`git tag -a`),不用 lightweight — annotated tag 带消息,在
`git fetch --tags` 时表现一致。

## CHANGELOG.md

每个 release 在 `CHANGELOG.md` 添加一条目,遵循
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式。
小节: `Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` /
`Security` — 空的小节直接省略。

文件顶部始终有一个 `[Unreleased]` 占位段,边迭代边往里加(别等到
发布前一次性补,容易漏)。Release 时把 `[Unreleased]` 改为
`[vX.Y.Z] — YYYY-MM-DD`,然后在顶部再加一个空的 `[Unreleased]`。

## Release 检查清单

1. **健康检查** — 当前 `main` 是绿的:回归测试通过
   (`python3 bin/_test_task_persistence.py` 等)、HTML 能干净重新渲
   染、server 能正常启动。
2. **CHANGELOG** — `[Unreleased]` 段已经列出本次发布的用户可见变更
   摘要。把它改名为 `[vX.Y.Z] — <今天日期>`。
3. **提交 CHANGELOG 改名**到 `main`。
4. **Fast-forward merge** `main → stable`(除非历史需要保留合并节
   点,否则不要 merge commit)。
5. **Tag** `stable`:`git tag -a vX.Y.Z -m vX.Y.Z`。
6. **Push** `git push origin stable main --tags`。
7. **重开** CHANGELOG 顶部的 `[Unreleased]` 段为下一轮迭代做准备。

## Hotfix 路径

`stable` 有个不能等下个常规 release 修的 bug:

```bash
git checkout stable
git switch -c hotfix/短名字
# 修复 + 提交 + CHANGELOG 加一段 [vX.Y.Z+1]
git switch stable && git merge --ff-only hotfix/短名字
git tag -a vX.Y.Z+1 -m vX.Y.Z+1
git push origin stable --tags
# 反向 merge 回 main,避免修复丢失
git switch main && git merge stable && git push
git branch -d hotfix/短名字
```

## 一个人的小工具,为什么 tag + 分支都要?

只用 tag 也行 — `git checkout v0.5.0` 进 detached HEAD,从那个状
态跑没问题。`stable` 分支额外存在的理由:大多数编辑器/IDE 把
detached HEAD 标记成"奇怪状态",而 `git pull stable` 是维护者已
经形成肌肉记忆的操作。

将来要去掉 `stable` 分支也容易(`git checkout` 最新 tag、删分支即
可)。**这份文档**是源头,分支名不是。
