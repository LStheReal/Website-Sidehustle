#!/bin/bash
# Build script: Assemble Cloudflare Pages deployment directory
# Copies onboarding dashboard + template assets into cf-dashboard/
# Landing page (Webflow) files are managed separately — NOT overwritten here.

set -e
cd "$(dirname "$0")"

DIST="cf-dashboard"

echo "Building Cloudflare Pages deployment..."

# Clean only dashboard-specific files (preserve landing page assets: index.html, index-mobile.html, assets/, hero-*.json)
rm -f "$DIST/onboarding.html" "$DIST/dashboard.css" "$DIST/dashboard.js"
rm -rf "$DIST/fonts" "$DIST/templates"

# Copy dashboard/onboarding static files
cp dashboard.html "$DIST/onboarding.html"
cp dashboard.css "$DIST/"
cp dashboard.js "$DIST/"

# Copy fonts
mkdir -p "$DIST/fonts"
cp fonts/* "$DIST/fonts/"

# Copy template directories for preview serving
for tpl in earlydog bia liveblocks loveseen; do
  src=".claude/skills/build-website-$tpl/template"
  dest="$DIST/templates/$tpl"
  if [ -d "$src" ]; then
    mkdir -p "$dest"
    cp -r "$src"/* "$dest/"
    echo "  Copied template: $tpl"
  fi
done

# Create _headers for caching
cat > "$DIST/_headers" << 'EOF'
/fonts/*
  Cache-Control: public, max-age=31536000

/templates/*/assets/*
  Cache-Control: public, max-age=86400

/api/*
  Cache-Control: no-store
EOF

echo ""
echo "Build complete! Files in $DIST/"
echo "Deploy with: npx wrangler pages deploy $DIST --project-name meinekmu"
