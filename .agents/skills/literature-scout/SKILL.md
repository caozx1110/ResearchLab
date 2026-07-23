---
name: literature-scout
description: 通过一次有界 OpenAlex Works 检索暂存外部论文候选；当用户明确要求按研究问题找论文、补充文献候选，或 program evidence request 需要外部文献发现时使用。
---

# Literature Scout

把外部检索结果放入 source-search staging，交给 runtime agent 后续去重、阅读和推荐。只记录来源 metadata；不创建 canonical paper，不判断 relevance、novelty 或质量。

## 工作流

1. 从用户问题或 program evidence request 提取一个明确检索主题；主题不清楚时先用自然语言补齐。
2. 私下运行 bundled scout，默认只取一页 25 项，任何一次请求最多 100 项；不自动翻页或 cursor crawl。
3. 默认排除 retracted works。只有内部审计明确需要时才启用私有 include-retracted 选项，并在后续阅读中保留撤稿事实。
4. 让脚本按 OpenAlex ID、其次 DOI 做稳定去重，并复用 source-search staging。重跑不得覆盖候选的人工 note 或 status。
5. 将候选交给 runtime agent 阅读、去重并形成待选建议；只有 source-intake 后续流程可以把用户接受的候选入库。

## 安全与边界

- 只接受运行时配置的 OpenAlex access；缺少配置、限流、网络错误或 malformed response 时 fail closed，不写空失败 stage。
- 不显示、持久化、记录或转述 access key、请求 URL、原始响应、内部路径、Python 命令或参数。
- 把 title、date/year、type、language、citation count、retraction flag、DOI/OpenAlex ID 与开放获取链接视为来源事实，不把 citation count 转成质量结论。
- 不把 staging candidate 当 canonical knowledge，不生成论文摘要、趋势、gap 或推荐结论。

## 用户反馈

成功时只用自然语言说明找到多少候选、已经暂存、下一步将由 Agent 去重阅读。失败时只说明可行动的自然语言原因，不暴露内部调用细节。不要新增或暗示新的公开 `kb` 动词。
