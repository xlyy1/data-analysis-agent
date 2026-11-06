# 消息表索引优化

## 背景

对话式分析 Agent 里最高频的操作之一，是按会话 ID 读取历史消息。一条对话可能积累几十到上百条消息，每次打开会话都要查一次。

最初的表结构只有主键索引，`conversation_id` 上没有索引。

## 定位

用 `EXPLAIN QUERY PLAN` 看执行计划：

```
SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at
```

结果：

```
SCAN messages
USE TEMP B-TREE FOR ORDER BY
```

两个问题：

1. `SCAN` 表示全表扫描，会话越多越慢
2. `USE TEMP B-TREE` 表示结果需要额外排序

## 方案

建联合索引，把「过滤字段」和「排序字段」放在一起：

```sql
CREATE INDEX idx_messages_conv_created ON messages(conversation_id, created_at);
```

选择联合索引而不是单列索引的原因：查询总是带 `ORDER BY created_at`。单列索引能过滤，但排序还要再来一次；联合索引里 `created_at` 已经有序，直接顺序读即可。

模型的 `__table_args__` 中同步声明，保证新建库也带索引：

```python
__table_args__ = (Index("idx_messages_conv_created", "conversation_id", "created_at"),)
```

## 验证

在副本库上造 5 万条消息（分散在 100 个会话），对同一查询跑 20 次取中位数：

| | 查询耗时 | 执行计划 |
|---|---|---|
| 加索引前 | 6.64 ms | `SCAN messages` + `USE TEMP B-TREE FOR ORDER BY` |
| 加索引后 | 2.57 ms | `SEARCH messages USING INDEX idx_messages_conv_created` |

执行计划从全表扫描变为索引查找，临时排序也消失了。

## 代价

- 写入变慢：每条 INSERT 需要维护索引
- 占用额外存储空间

消息表是读多写少的场景，取舍上偏向查询性能，因此值得。

## 复现方式

```python
cur.execute("EXPLAIN QUERY PLAN SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at", ("conv-1",))
print(cur.fetchall())
```
