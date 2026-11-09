# 中文技术检索

文章全文搜索与 RAG 的 BM25 分路共用中文分析配置，资源在 `src/main/resources/elasticsearch/`：

- `easyjob-technical.dic`：IK 扩展技术词，如缓存穿透、缓存击穿、倒排索引、检索增强生成。词典不是按字段自动启用，先注册到 IK 的 `ext_dict`，再由使用 IK 的分析器加载。
- `easyjob-synonyms.txt`：查询侧等价表达，如 `es, elasticsearch`、`springboot, spring boot`、`rag, 检索增强生成`。不同故障和不同框架不能当同义词。
- `chinese-analysis.json`：索引分析器 `ik_max_word → cjk_width → lowercase`；查询分析器 `ik_smart → cjk_width → lowercase → synonym_graph`。同义词不进入索引分析器。

文章索引的 `title/summary/content`、分块索引的 `title/chunk_content/section_path` 增加 `.zh` 子字段。检索优先查这些字段，保留低权重旧字段以兼容迁移前的索引。标题高亮优先使用 `title.zh`，兼容旧标题字段。索引名仍为 `article` 和 `article_vectors`，文档来源、分块 ID、版本校验和 RRF 去重方式保持一致。

## 首次安装或升级已有索引

安装匹配 ES 版本的 IK 插件，然后在项目根目录执行（Windows 可使用虚拟环境的 Python）：

```powershell
python scripts/install-chinese-analysis.py --es-home "D:\path\to\elasticsearch"
```

安装器保留已有 IK 字典项和远程词典配置，追加项目词典，并将同义词复制到 ES `config/analysis/`。修改前的文件保存在 `logs/chinese-search-install/`；`--check` 只检查。IK 的 XML 配置必须保留 Java Properties 的 DOCTYPE。多节点必须在每个节点安装相同资源。

静态 IK 词典更新后重启 ES。项目一键启动在启动未运行的 ES 前自动安装资源；已经运行的 ES 不会被一键启动静默重启。随后执行：

```powershell
python scripts/chinese-search.py verify --output logs/chinese-search-verify.json
python scripts/chinese-search.py plan --output logs/chinese-search-plan.json
```

`verify` 使用随机命名的独立索引测试技术词、同义词、高亮和旧索引迁移，并清理自己的测试索引；不调用模型。`plan` 只读取两个业务索引的文档数及来源指纹。

已有文档不会因新增 multi-field 自动补齐倒排数据。停止 Java/Python 写入服务，备份并回填：

```powershell
python scripts/chinese-search.py apply --output logs/chinese-search-migration.json
```

维护脚本仅连接本机 ES，拒绝 Java8080/Python8000仍运行的情况；其他实例或外部写入者也需由运维停止。逐个索引执行写保护、克隆备份、关闭索引添加分析器、重新打开、追加子字段、`update_by_query` 回填，并比较原文档 ID、完整 `_source` 与向量指纹。ES9向量源回查会恢复实际存储的 float32，因此指纹以此精度比较。全过程不重新调用 Embedding；备份保留在 `easyjob_zh_backup_*`，报告记录具体名称。失败不会自动删除原索引或备份，须检查报告后再处理。

确认成功后重新构建并启动 Java/Python。新建索引直接包含完整配置；再次 `apply` 对已核验且资源一致的索引跳过回填。回填期间搜索可能短暂不可用，安排维护窗口执行。

## 后续调整

只修改同义词时，先用安装器同步文件，再执行：

```powershell
python scripts/chinese-search.py reload --output logs/chinese-search-reload.json
python scripts/chinese-search.py verify --output logs/chinese-search-verify.json
```

`synonym_graph` 设置了 `updateable`，不需重新建索引，重载后清理请求缓存。词条必须能被当前 tokenizer 正确分析；重载失败时恢复安装器留下的旧文件后再次重载。

修改静态技术词典或索引分析器则需重启 ES并重新回填现有文档；安装器只复制文件，不会重建倒排索引。应用提示未装分析器时，应先完成安装/迁移，不要手工修改生产字段类型。

## 验证范围

13 条合成查询用于确认缩写、中文技术词与标题高亮可用，包含缓存穿透/击穿/雪崩的区分；另验证 6 个中文复合词、3 组分析器同义词及含向量的旧文档迁移。这些是功能回归，不能据此声称生产召回率提升。真实召回率仍需按业务问题标注相关文章/分块并运行已有 RAG 评测。

CI 的 ES8.15.5 镜像包含同一词典/同义词；本机验证使用 ES9.2.4。离线回归检查安装幂等、配置保留、备份失败解锁、设置失败重新打开和 ES9 向量回查；Java 测试验证映射兼容及 XML 可由 `Properties.loadFromXML` 读取。
