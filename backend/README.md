# DraftMind Django Backend

## 快速启动

```bash
cd /home/ubuntu/draftmind_django
sudo pip3 install -r requirements.txt
python3.11 manage.py migrate
python3.11 manage.py runserver 127.0.0.1:5000
```

健康检查：

```bash
curl http://127.0.0.1:5000/
```

预期响应：

```json
{"status":"ok"}
```

## 兼容 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/` | 健康检查 |
| `POST` | `/conversation/new` | 上传图纸并创建解析任务 |
| `GET` | `/conversation/list` | 获取历史图纸列表 |
| `GET` | `/conversation/<conv_uuid>/info` | 获取解析结果 |
| `POST` | `/conversation/<conv_uuid>/review` | 合规审查 |
| `POST` | `/conversation/<conv_uuid>/ask` | 图纸问答 |
| `GET` | `/job/<job_id>/status` | 查询任务状态 |
| `POST` | `/job/<job_id>/prioritize` | 提升任务优先级 |
| `GET` | `/knowledge/similar/<conv_uuid>` | 相似图纸推荐 |
| `POST` | `/knowledge/search` | 搜索知识库 |
| `GET` | `/uploads/<filename>` | 访问本地上传图片 |

## 验证

```bash
python3.11 manage.py check
python3.11 test_api_compatibility.py
python3.11 -m compileall draftmind_backend drawings
```

当前版本已通过上述检查。
