const { notarize } = require("@electron/notarize");

exports.default = async function notarizeMac(context) {
  if (context.electronPlatformName !== "darwin") return;
  if (process.env.OPENTALKING_MAC_NOTARIZE !== "1" && process.env.OPENTALKING_MAC_NOTARIZE !== "true") {
    console.log("  • Notarization skipped: OPENTALKING_MAC_NOTARIZE is not enabled");
    return;
  }

  const appBundleId = process.env.OPENTALKING_MAC_BUNDLE_ID || "cc.opentalking.desktop";
  const appName = context.packager.appInfo.productFilename;
  const appPath = `${context.appOutDir}/${appName}.app`;

  if (process.env.APPLE_KEYCHAIN_PROFILE) {
    await notarize({
      tool: "notarytool",
      appBundleId,
      appPath,
      keychainProfile: process.env.APPLE_KEYCHAIN_PROFILE,
      keychain: process.env.APPLE_KEYCHAIN || undefined,
    });
    return;
  }

  if (process.env.APPLE_API_KEY && process.env.APPLE_API_KEY_ID && process.env.APPLE_API_ISSUER) {
    await notarize({
      tool: "notarytool",
      appBundleId,
      appPath,
      appleApiKey: process.env.APPLE_API_KEY,
      appleApiKeyId: process.env.APPLE_API_KEY_ID,
      appleApiIssuer: process.env.APPLE_API_ISSUER,
    });
    return;
  }

  const appleIdPassword = process.env.APPLE_APP_SPECIFIC_PASSWORD || process.env.APPLE_PASSWORD;
  if (process.env.APPLE_ID && appleIdPassword && process.env.APPLE_TEAM_ID) {
    await notarize({
      tool: "notarytool",
      appBundleId,
      appPath,
      appleId: process.env.APPLE_ID,
      appleIdPassword,
      teamId: process.env.APPLE_TEAM_ID,
    });
    return;
  }

  throw new Error(
    "OPENTALKING_MAC_NOTARIZE requires APPLE_KEYCHAIN_PROFILE, APPLE_API_KEY/APPLE_API_KEY_ID/APPLE_API_ISSUER, or APPLE_ID/APPLE_APP_SPECIFIC_PASSWORD/APPLE_TEAM_ID.",
  );
};
