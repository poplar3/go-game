#!/usr/bin/env bash
# Проверка на эмуляторе: KataGo отвечает на запрос, приложение запускается и поднимает ИИ.
set -euo pipefail
adb wait-for-device

echo "== KataGo напрямую =="
adb push katago-x86_64/libkatago.so /data/local/tmp/katago >/dev/null
adb shell chmod 755 /data/local/tmp/katago
unzip -o -q dist/*.apk 'assets/katago/*' -d apk
SRC=$(ls apk/assets/katago/)
MODEL=${SRC%.gzdata}
adb push "apk/assets/katago/$SRC" "/data/local/tmp/$MODEL" >/dev/null
printf 'logToStderr = false\nlogDir = /data/local/tmp/logs\nnumAnalysisThreads = 1\nnumSearchThreadsPerAnalysisThread = 2\nnnMaxBatchSize = 8\n' > analysis.cfg
adb push analysis.cfg /data/local/tmp/ >/dev/null
echo '{"id":"t1","moves":[["B","E5"]],"rules":"chinese","komi":7.5,"boardXSize":9,"boardYSize":9,"maxVisits":30}' > q.json
adb push q.json /data/local/tmp/ >/dev/null
adb shell "cd /data/local/tmp && ./katago analysis -config analysis.cfg -model $MODEL < q.json" > out.txt 2> err.txt || true
tail -5 err.txt || true
head -c 600 out.txt; echo
grep -q '"id":"t1"' out.txt

echo "== Приложение =="
adb install -r dist/*.apk
adb logcat -c
adb shell am start -n ru.gotrainer/.MainActivity --ez selftest true
for i in $(seq 1 120); do
  if adb logcat -d -s GoTrainer:D | grep -q "\[selftest\]"; then break; fi
  sleep 2
done
adb logcat -d -s GoTrainer:D | tail -40
adb logcat -d -s GoTrainer:D | grep -q "\[selftest\] analysis ok"
if adb logcat -d -s GoTrainer:D | grep -q "library Error"; then echo "Библиотека задач не загрузилась"; exit 1; fi
echo "OK: приложение запустило KataGo"
