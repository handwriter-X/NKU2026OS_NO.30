# 本次报告补证：DTB 调试与测试敏感性

采集日期：2026-10-26。内核和 runner 沿用 `328fd3a` 的当前实现；没有覆盖 `code/evidence/` 中已有的功能、启动或 QEMU 源码日志。

## DTB 三容量实测

在 Ubuntu 的 `lab2/code` 执行：

```bash
python3 ../report/tools/capture_dtb.py
```

脚本构建当前 Best-Fit/case0，分别启动 64、128、256 MiB 的 QEMU；在物理入口、dtb_init、dtb_parse、run_selftests 停留，观察启动参数、高映射指针、FDT 头和 memory/reg。GDB Python 独立解码 reg，再与内核原生解析函数的实际返回值/输出比较。最后继续执行到正常自测全部完成。

| 容量 | GDB 原始日志 | 串口原始日志 | 命令及 SHA256 |
|---|---|---|---|
| 64M | [gdb.log](dtb-64M/gdb.log) | [qemu.log](dtb-64M/qemu.log) | [manifest.json](dtb-64M/manifest.json) |
| 128M | [gdb.log](dtb-128M/gdb.log) | [qemu.log](dtb-128M/qemu.log) | [manifest.json](dtb-128M/manifest.json) |
| 256M | [gdb.log](dtb-256M/gdb.log) | [qemu.log](dtb-256M/qemu.log) | [manifest.json](dtb-256M/manifest.json) |

当前构建分别观察到 15567、31727、31727 个 FREE 页；这些数字依赖内核大小，不作为其他构建的固定预期。256M 的发现容量为 256 MiB，管理上限仍为 128 MiB。

## 四项故障注入

```bash
python3 ../report/tools/check_test_sensitivity.py
```

脚本复制代码到 Linux 临时目录，排除现有 obj/bin/evidence，每次只替换一处源代码；在临时副本使用原 runner 构建并执行。要求非零退出，而且日志包含预定失败原因，才能判为该项反向验证成功。原仓库内核不修改，临时副本自动清理。

| 故障 | 结果与原始日志 |
|---|---|
| Best-Fit 退化成 First-Fit | [记录](test-sensitivity/best-fit-becomes-first-fit/result.json)、[runner](test-sensitivity/best-fit-becomes-first-fit/runner.log)、[guest](test-sensitivity/best-fit-becomes-first-fit/guest.log) |
| Buddy 按请求而非实际跨度扣页 | [记录](test-sensitivity/buddy-counts-request-not-span/result.json)、[runner](test-sensitivity/buddy-counts-request-not-span/runner.log)、[guest](test-sensitivity/buddy-counts-request-not-span/guest.log) |
| SLUB 不归还空页 | [记录](test-sensitivity/slub-keeps-empty-pages/result.json)、[runner](test-sensitivity/slub-keeps-empty-pages/runner.log)、[guest](test-sensitivity/slub-keeps-empty-pages/guest.log) |
| EXPECT 对应错误 panic | [记录](test-sensitivity/wrong-panic-is-not-success/result.json)、[runner](test-sensitivity/wrong-panic-is-not-success/runner.log)、[guest](test-sensitivity/wrong-panic-is-not-success/guest.log) |

汇总：[summary.json](test-sensitivity/summary.json)。4/4 成功的含义是四个错误副本均被测试拒绝，而不是错误代码通过了功能测试。该集合只说明对应检查有实际敏感性，没有证明覆盖所有潜在缺陷。

## 配图来源

新图的原始来源、选取行号与 SHA256 见 [image-manifest.json](../images/image-manifest.json)。示意图使用同目录 DOT 源文件；日志图是原始记录的排版，不冒充现场终端截图。主报告引用的既有浏览器截图另有原始 QEMU 源码日志出处。
