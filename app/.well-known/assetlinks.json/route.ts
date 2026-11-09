// Digital Asset Links: tells Android that the KTRADES app may open this site
// full-screen (Trusted Web Activity) without a browser address bar.
//
// Set these env vars on Vercel, then redeploy:
//   TWA_PACKAGE_NAME          e.g. app.vercel.ktrades_signals.twa
//   TWA_SHA256_FINGERPRINTS   comma-separated SHA-256 cert fingerprints.
//     Use the "App signing key certificate" fingerprint from
//     Play Console → Test and release → App integrity, plus your upload key's
//     fingerprint if you also sideload builds signed locally.
export function GET() {
  const packageName = process.env.TWA_PACKAGE_NAME?.trim();
  const fingerprints = (process.env.TWA_SHA256_FINGERPRINTS ?? "")
    .split(",")
    .map((f) => f.trim().toUpperCase())
    .filter(Boolean);

  const statements =
    packageName && fingerprints.length
      ? [
          {
            relation: ["delegate_permission/common.handle_all_urls"],
            target: {
              namespace: "android_app",
              package_name: packageName,
              sha256_cert_fingerprints: fingerprints,
            },
          },
        ]
      : [];

  return Response.json(statements);
}
