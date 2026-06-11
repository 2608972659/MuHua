# README

## 项目概述

- 2000+条原子知识全部向量化后存入入ES数据库里 维度768维 索引名为atomic_knowledge_base_py

- 与病例概况匹配的10条原子知识会加入[1]引用样式来返回，最终输出的建议结尾也会加入[1]与之匹配溯源

- 输入输入均为JSON格式内容 详见实例

## 源码打包导出

```bash
# 在“生成”文件夹构建（Nuitka 编译）
docker-compose -p generation build generation-api

# 导出镜像
docker save generation-generation-api:latest -o generation-api.tar
# 产物为generation-api.tar
```

---

将本项目部署到新服务器，需要传输以下 5 个文件/目录：

| 文件/目录                   | 说明                               |
| --------------------------- | ---------------------------------- |
| `generation-api.tar`        | API 的 Docker 镜像包               |
| `es_existing_data/`         | 已有且向量化的原子知识数据         |
| `docker-compose.deploy.yml` | 部署用 compose 配置                |
| `.env`                      | 环境变量（含 API 密钥）            |
| `Dockerfile.es`             | ES 镜像构建文件（IK 中文分词插件） |

---

## 部署步骤

### 1. 新服务器安装 Docker

```bash
# 验证环境
docker --version
docker compose version
```

### 2. 传输项目目录

### 3. 加载镜像 + 构建 ES 插件镜像

```bash
# 加载 API 镜像
docker load < generation-api.tar

# 构建带 IK 插件的 ES 镜像
docker build -t elasticsearch-ik:8.10.0 -f Dockerfile.es .
```

### 4. 修正 ES 数据目录权限

ES 容器内以 UID 1000 运行，Linux 上必须改权限：

```bash
chown -R 1000:1000 es_existing_data
```

### 5. 启动

```bash
# 删除可能遗留的锁文件
rm -f es_existing_data/node.lock

# 启动
docker compose -f docker-compose.deploy.yml --env-file .env up -d
```

### 6. 验证

```bash
# 容器状态
docker ps

# 验证 ES
source .env
curl -s -u "elastic:$ES_PASSWORD" http://localhost:9200/_cluster/health

# 验证 API
curl -s http://localhost:8001
```

---

## 注意事项

### ES 内部用 HTTP 而非 HTTPS

API 配置的 `ES_URL=http://elasticsearch:9200`。如需对外暴露 ES 端口，建议额外配置 SSL。

### IK 插件数据兼容

数据用了 `ik_max_word` 分词器，必须使用 `elasticsearch-ik:8.10.0` 镜像（由 `Dockerfile.es` 构建）。

### 部署常见问题

| 问题                       | 原因             | 解决                                    |
| -------------------------- | ---------------- | --------------------------------------- |
| ES 报权限错误              | 数据目录权限不对 | `chown -R 1000:1000 es_existing_data`   |
| ES 报 `node.lock`          | 上次异常退出残留 | 删除 `es_existing_data/node.lock`       |
| ES 报 `ik_max_word` 未配置 | 未装 IK 插件     | 确保用了 `elasticsearch-ik:8.10.0`      |
| API 连不上 ES              | 启动顺序         | `docker compose restart generation-api` |

### 安全提醒

- `.env` 含 API 密钥，**不要提交到 Git**
- 生产环境建议修改 ES 密码

### 存在的问题

- 模型生成建议以\"- \"开头无法保证输出格式的稳定性  修改提示词后现在的项目输出无“-”开头
- 原子知识覆盖不全，生成的建议与给出的的原子知识仍有些不对应，或者可能输出建议数量变少
- 生成一次总时间大约需要30s
