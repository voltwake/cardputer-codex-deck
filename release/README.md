# Codex Deck 发布

`compatibility.json` 由根目录 `version.json` 生成；`appcast.xml` 是 Sparkle 稳定更新源。

公开 tag 必须与 `version.json.release` 完全一致。正式产物包括签名并公证的
App ZIP、面向用户的 DMG、固件 BIN、兼容性清单、第三方声明、发布 manifest
和 `SHA256SUMS`。普通用户优先安装 DMG；Sparkle 使用 ZIP。

本机候选构建：

```sh
CODE_SIGN_IDENTITY="Apple Development: …" bridge/macos/scripts/release.sh
```

公开发布必须使用 `Developer ID Application`，并先把 Notary 凭据保存到 Keychain：

```sh
xcrun notarytool store-credentials cardbridge-notary
REQUIRE_NOTARIZATION=1 \
NOTARY_PROFILE=cardbridge-notary \
CODE_SIGN_IDENTITY="Developer ID Application: …" \
bridge/macos/scripts/release.sh
```

Sparkle 私钥只保存在本机 Keychain，账户名固定为 `com.voltwake.cardbridge`；仓库仅保存公钥。

发布前还必须审阅根目录 `THIRD_PARTY_NOTICES.md`、
`firmware/m5stack-cardputer-adv/assets/ASSET_SOURCES.md`
和 `SECURITY.md`，并确认 GitHub Release 中的所有文件都出现在校验清单中。
