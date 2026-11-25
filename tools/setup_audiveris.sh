#!/usr/bin/env bash
# Build Audiveris (open-source OMR) from source. Needs JDK 25 and network access to
# github.com (git clone), Maven Central and repository.jboss.org (jai-core).
set -euo pipefail
DEST=${1:-$HOME/audiveris}
if ! [ -x /usr/lib/jvm/java-25-openjdk-amd64/bin/java ]; then
  sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openjdk-25-jdk-headless
fi
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk-amd64
[ -d "$DEST/.git" ] || GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/Audiveris/audiveris "$DEST"
(cd "$DEST" && ./gradlew --no-daemon -q :app:installDist)
echo "Audiveris: $DEST/app/build/install/app/bin/Audiveris"
echo "Run:  JAVA_HOME=$JAVA_HOME $DEST/app/build/install/app/bin/Audiveris -batch -export -output OUTDIR -- page.png"
