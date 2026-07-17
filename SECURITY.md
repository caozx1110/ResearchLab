# Security

以下治理红线也是安全相关不变量：

- AI 不能自我确认。
- 确认必须提供显式 `--evidence`。
- AI inference / evaluation 在人工确认门控通过前保持 `pending_user_confirmation`。

请通过 GitHub issues 报告安全或治理问题，不要在 issue 中包含私有源数据。
