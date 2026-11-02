package ru.gotrainer;

import android.content.pm.PackageInfo;
import android.content.res.AssetManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Мост между страницей игры и KataGo. KataGo собран для Android как отдельная программа
 * (libkatago.so в папке нативных библиотек приложения) и работает в режиме анализа:
 * запросы JSON уходят ему на вход, ответы построчно передаются в JavaScript.
 */
public class KataGoBridge {
    private final MainActivity activity;
    private final WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final File dir;
    private Process proc;
    private BufferedWriter stdin;
    private volatile int generation = 0;
    private volatile boolean downloading = false;
    /** Все обращения к процессу идут по очереди в одном потоке, чтобы запросы не перепутались. */
    private final ExecutorService exec = Executors.newSingleThreadExecutor();

    KataGoBridge(MainActivity activity, WebView web) {
        this.activity = activity;
        this.web = web;
        this.dir = new File(activity.getFilesDir(), "katago");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
    }

    private File binary() {
        return new File(activity.getApplicationInfo().nativeLibraryDir, "libkatago.so");
    }

    private void js(String code) {
        ui.post(() -> web.evaluateJavascript(code, null));
    }

    private void status(String state, String text) {
        js("window.__kg && window.__kg.onStatus(" + JSONObject.quote(state) + "," + JSONObject.quote(text) + ")");
    }

    /** Нейросети, встроенные в APK (assets/katago), копируются в папку приложения один раз. */
    private void copyBundledModels() {
        AssetManager am = activity.getAssets();
        try {
            String[] names = am.list("katago");
            if (names == null) return;
            for (String n : names) {
                // в APK файл лежит как *.bin.gz.gzdata (иначе сборщик распаковал бы .gz)
                File out = new File(dir, n.endsWith(".gzdata") ? n.substring(0, n.length() - 7) : n);
                if (out.exists() && out.length() > 0) continue;
                File tmp = new File(dir, out.getName() + ".part");
                try (InputStream in = am.open("katago/" + n); OutputStream o = new FileOutputStream(tmp)) {
                    byte[] buf = new byte[1 << 16];
                    int r;
                    while ((r = in.read(buf)) > 0) o.write(buf, 0, r);
                }
                //noinspection ResultOfMethodCallIgnored
                tmp.renameTo(out);
            }
        } catch (Exception ignored) {
        }
    }

    private List<File> models() {
        List<File> res = new ArrayList<>();
        File[] fs = dir.listFiles();
        if (fs == null) return res;
        for (File f : fs) {
            String n = f.getName();
            if ((n.endsWith(".bin.gz") || n.endsWith(".txt.gz")) && f.length() > 0) res.add(f);
        }
        return res;
    }

    @JavascriptInterface
    public String engineInfo() {
        copyBundledModels();
        try {
            JSONObject o = new JSONObject();
            o.put("hasBinary", binary().exists());
            o.put("abi", Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "");
            o.put("cores", Runtime.getRuntime().availableProcessors());
            JSONArray arr = new JSONArray();
            for (File f : models()) {
                JSONObject m = new JSONObject();
                m.put("name", f.getName());
                m.put("size", f.length());
                arr.put(m);
            }
            o.put("models", arr);
            return o.toString();
        } catch (Exception e) {
            return "{}";
        }
    }

    @JavascriptInterface
    public String appVersion() {
        try {
            PackageInfo pi = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0);
            return pi.versionName;
        } catch (Exception e) {
            return "";
        }
    }

    @JavascriptInterface
    public void engineStart(String settingsJson) {
        exec.execute(() -> startInternal(settingsJson));
    }

    private void startInternal(String settingsJson) {
        stopInternal();
        final int gen = ++generation;
        copyBundledModels();
        File bin = binary();
        if (!bin.exists()) {
            status("error", "KataGo не собран для процессора этого телефона — играет встроенный бот.");
            return;
        }
        String wanted = "";
        int threads = 0;
        try {
            JSONObject s = new JSONObject(settingsJson);
            wanted = s.optString("model", "");
            threads = s.optInt("threads", 0);
        } catch (Exception ignored) {
        }
        File model = null;
        for (File f : models()) {
            if (f.getName().equals(wanted)) model = f;
        }
        if (model == null) {
            for (File f : models()) {
                if (model == null || f.length() < model.length()) model = f; // по умолчанию самая быстрая
            }
        }
        if (model == null) {
            status("error", "Нейросеть KataGo не найдена — играет встроенный бот. Скачайте нейросеть в «Настройках».");
            return;
        }
        int cores = Runtime.getRuntime().availableProcessors();
        if (threads <= 0) threads = Math.max(1, Math.min(4, cores / 2));
        File cfg = new File(dir, "analysis.cfg");
        String config = "# Сгенерировано игрой автоматически\n"
                + "logToStderr = false\n"
                + "logDir = " + new File(dir, "logs").getAbsolutePath() + "\n"
                + "reportAnalysisWinratesAs = BLACK\n"
                + "maxVisits = 500\n"
                + "numAnalysisThreads = 2\n"
                + "numSearchThreadsPerAnalysisThread = " + threads + "\n"
                + "nnMaxBatchSize = 8\n"
                + "nnCacheSizePowerOfTwo = 18\n"
                + "nnMutexPoolSizePowerOfTwo = 14\n"
                + "nnRandomize = true\n";
        try (OutputStream o = new FileOutputStream(cfg)) {
            o.write(config.getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) {
            status("error", "Не удалось записать настройки KataGo: " + e.getMessage());
            return;
        }
        status("starting", "Запускаю ИИ KataGo (" + model.getName() + ")…");
        final String modelName = model.getName();
        try {
            ProcessBuilder pb = new ProcessBuilder(bin.getAbsolutePath(), "analysis",
                    "-config", cfg.getAbsolutePath(), "-model", model.getAbsolutePath());
            pb.directory(dir);
            final Process p = pb.start();
            proc = p;
            stdin = new BufferedWriter(new OutputStreamWriter(p.getOutputStream(), StandardCharsets.UTF_8));
            final LinkedList<String> tail = new LinkedList<>();
            final boolean[] ready = {false};
            Thread err = new Thread(() -> {
                try (BufferedReader r = new BufferedReader(new InputStreamReader(p.getErrorStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = r.readLine()) != null) {
                        synchronized (tail) {
                            tail.add(line);
                            if (tail.size() > 12) tail.removeFirst();
                        }
                        if (!ready[0] && line.contains("Started, ready")) {
                            ready[0] = true;
                            if (gen == generation) status("ready", "ИИ KataGo готов (" + modelName + ")");
                        }
                    }
                } catch (Exception ignored) {
                }
                if (gen == generation) {
                    String t;
                    synchronized (tail) {
                        t = String.join("\n", tail);
                    }
                    status("error", (ready[0] ? "KataGo остановился" : "Не удалось запустить KataGo")
                            + (t.isEmpty() ? "" : ": " + t) + ". Играет встроенный бот.");
                }
            }, "katago-err");
            err.start();
            Thread out = new Thread(() -> {
                try (BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = r.readLine()) != null) {
                        if (gen != generation) break;
                        if (!line.startsWith("{")) continue;
                        js("window.__kg && window.__kg.onLine(" + JSONObject.quote(line) + ")");
                    }
                } catch (Exception ignored) {
                }
            }, "katago-out");
            out.start();
        } catch (Exception e) {
            status("error", "Не удалось запустить KataGo: " + e.getMessage() + ". Играет встроенный бот.");
        }
    }

    @JavascriptInterface
    public void engineQuery(String line) {
        exec.execute(() -> {
            BufferedWriter w = stdin;
            if (w == null) return;
            try {
                w.write(line);
                w.write("\n");
                w.flush();
            } catch (Exception ignored) {
            }
        });
    }

    @JavascriptInterface
    public void engineStop() {
        exec.execute(() -> {
            generation++;
            stopInternal();
        });
    }

    private void stopInternal() {
        if (proc != null) {
            try {
                stdin.close();
            } catch (Exception ignored) {
            }
            proc.destroy();
            proc = null;
            stdin = null;
        }
    }

    void shutdown() {
        generation++;
        stopInternal();
    }

    @JavascriptInterface
    public void saveFile(String name, String text) {
        ui.post(() -> activity.saveFile(name, text));
    }

    /** Скачивание дополнительной нейросети (один раз, дальше всё работает без интернета). */
    @JavascriptInterface
    public void downloadModel(String url, String name) {
        if (downloading) return;
        downloading = true;
        new Thread(() -> {
            File part = new File(dir, name + ".part");
            try {
                HttpURLConnection c = open(url);
                long total = c.getContentLengthLong();
                long done = 0, lastReport = 0;
                try (InputStream in = c.getInputStream(); OutputStream o = new FileOutputStream(part)) {
                    byte[] buf = new byte[1 << 16];
                    int r;
                    while ((r = in.read(buf)) > 0) {
                        o.write(buf, 0, r);
                        done += r;
                        if (done - lastReport > (1 << 20)) {
                            lastReport = done;
                            js("window.__kg.onDownload(" + JSONObject.quote(name) + "," + done + "," + total + ",'progress')");
                        }
                    }
                }
                File out = new File(dir, name);
                if (!part.renameTo(out)) throw new Exception("не удалось сохранить файл");
                js("window.__kg.onDownload(" + JSONObject.quote(name) + ",0,0,'done')");
            } catch (Exception e) {
                //noinspection ResultOfMethodCallIgnored
                part.delete();
                js("window.__kg.onDownload(" + JSONObject.quote(name) + "," + JSONObject.quote(String.valueOf(e.getMessage())) + ",0,'error')");
            } finally {
                downloading = false;
            }
        }, "download").start();
    }

    private static HttpURLConnection open(String url) throws Exception {
        String u = url;
        for (int k = 0; k < 6; k++) {
            HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(30000);
            c.setReadTimeout(60000);
            c.setRequestProperty("User-Agent", "GoTrainer-Android");
            int code = c.getResponseCode();
            if (code >= 300 && code < 400) {
                u = new URL(new URL(u), c.getHeaderField("Location")).toString();
                c.disconnect();
                continue;
            }
            if (code != 200) throw new Exception("HTTP " + code);
            return c;
        }
        throw new Exception("слишком много перенаправлений");
    }
}
