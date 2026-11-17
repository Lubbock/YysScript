#! /bin/bash
#for i in {1..5}
#do
#done
path="$(cd "$(dirname $0)";pwd)"
cd ${path}
/usr/local/bin/play ./resource/beep.mp3 trim 0.0 10
