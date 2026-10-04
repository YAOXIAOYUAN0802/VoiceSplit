# Contributors / 贡献者

## YAOXIAOYUAN0802

- GitHub: [@YAOXIAOYUAN0802](https://github.com/YAOXIAOYUAN0802)
- 项目发起人、产品负责人与测试者：提出全部需求与验收标准（分离质量、人声突显、极端隔离、
  片段替换、图形界面、exe 打包、开源发布），提供真实素材做端到端实测，并从使用者角度
  报告问题（背景音乐残留、音频尾部失效、片段替换错位等）

## DeepSeek Harness (AI pair programmer)

- 在 [DeepSeek Harness](https://github.com/deepseek-ai) 中作为编码代理协作完成
- 负责架构设计与代码实现：MDX-Net 推理与自动 FFT 参数适配、互补式与掩蔽式两条提取路径、
  三档强度（含两趟迭代极端隔离）、多声道中置声道先验、软限幅与互补渲染、片段替换对齐、
  tkinter 图形界面、自检与测试、PyInstaller 打包、模型下载/发布脚本、README 与配图

---

## 说明

本项目由人机协作完成：需求、取舍与验收来自 **YAOXIAOYUAN0802**；实现与调试由 **DeepSeek
Harness** 代理在其指导下完成。开发过程中的关键决策（例如为什么用掩蔽式替代互补式、
为什么 5.1 素材要用中置声道做先验、为什么极端隔离要跑两趟迭代）都记录在
[CHANGELOG.md](CHANGELOG.md) 与提交历史中。
