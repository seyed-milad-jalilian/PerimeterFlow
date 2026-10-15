# شناسنامه رسمی پروژه

* **نام پروژه / پلتفرم:** PerimeterFlow
* **مخزن گیت‌هاب:** https://github.com/seyed-milad-jalilian/perimeterflow
* **زیرعنوان مهندسی (Cloud / DevOps CV):** Cloud-Native Distributed MFD Simulation & Perimeter Control Engine
* **عنوان آکادمیک (Research / PhD CV):** Bias-Aware MFD-Based Macroscopic Traffic State Estimation and Latency-Compensated Perimeter Control under Non-Uniform Sparse Probes
* **پشته فنی (Tech Stack):** Kubernetes (k3s), Argo Workflows, SUMO, Python 3.12, TypeScript, Redis, Prometheus, LaTeX
* **اساتید و گروه‌های تحقیقاتی هدف:** Mehdi Keyvan-Ekbatani (Canterbury), Hai Vu (Monash), Meead Saberi (UNSW), Minh Kieu (Auckland).

---

# فصل ۰: منشور معماری، گاردریل‌ها و تخصیص منابع سخت‌افزاری

## ۱. سهمیه‌بندی منابع روی سرور OCI Always Free (4 OCPU ARM64, 24GB RAM)
سقف مصرف حافظه کل بارهای کاری کلاستر روی $15.0\,\text{GiB}$ قفل شده است تا حاشیه امنیتی قطعی معادل $9.0\,\text{GiB}$ برای هسته لینوکس و کش سیستم‌عامل حفظ شود؛ بدین ترتیب رخداد خطای `OOMKilled` ناممکن خواهد بود:

| سرویس / مؤلفه کلاستر k3s | نوع بار کاری | سهمیه CPU (requests / limits) | سهمیه RAM (requests / limits) | تدبیر رفع گلوگاه |
| :--- | :--- | :--- | :--- | :--- |
| **OS Kernel + k3s Control Plane** | دائمی (Systemd) | 250m / 500m | 1.2Gi / 1.8Gi | غیرفعال‌سازی Traefik و متریک‌سرور پیش‌فرض |
| **Argo CD + Kyverno Controller** | دائمی (argocd) | 200m / 500m | 768Mi / 1.2Gi | اعتبارسنجی خودکار امضای Cosign در زمان اجرا |
| **Prometheus Operator + Grafana** | دائمی (monitoring) | 300m / 600m | 1.5Gi / 2.5Gi | تنظیم دوره نگهداری ۳ روزه داده‌ها (`retention: 3d`) |
| **Redis In-Memory Buffer** | دائمی (perimeterflow) | 100m / 300m | 512Mi / 1.0Gi | بافر حلقوی ذخیره سوابق کنترلی برای پیش‌بین اسمیت |
| **Exporter & Metrics API (FastAPI)** | دائمی (perimeterflow) | 100m / 300m | 256Mi / 512Mi | اکسپورت متریک‌های NRMSE و گیت کیفیت به پرومتئوس |
| **IndexedJob Workers (SUMO Headless)** | دسته‌ای (۴ پاد موازی) | 1600m / 2000m (جمعاً) | 4.0Gi / 8.0Gi (جمعاً) | تخصیص سقف ۲ گیگابایت حافظه به هر ورکر شبیه‌سازی |
| **جمع کل در اوج بار شبیه‌سازی** | — | **2550m / 4200m** | **8.2Gi / 15.0Gi (از 24.0Gi)** | بدون ریسک کرش یا کندی سیستم |

## ۲. پنج گارد علمی و داده‌ای
1. **تفکیک قطعی سیدها (حذف تله آماری $N=1$):** ۱۰ سید اول (`Seeds 1..10`) صرفاً برای کالیبراسیون و تیون کردن منصفانه کنترلرها استفاده می‌شوند. ۳۰ سید مستقل (`Seeds 11..40`) برای ارزیابی نهایی، محاسبه فواصل اطمینان ۹۵٪ بوت‌استرپ و آزمون ویلکاکسون قفل می‌مانند.
2. **پرهیز از ارقام فرضی پیش از اجرا:** تا پیش از اجرای واقعی شبیه‌سازی‌ها، تمام فیلدهای عددی نتایج در اسکیما `null` بوده و وضعیت سند `"status": "planned"` است.
3. **زمین حقیقت ۱۰۰٪ معلوم (Known Ground Truth):** شبیه‌سازی دو مخزنی در SUMO مسیرهای تمام خودروها را ذخیره می‌کند؛ سپس پروب‌ها ($1\%$ تا $10\%$) و نویز GPS بر آن اعمال می‌شوند تا خطای واقعی قابل محاسبه باشد.
4. **تطابق عددی $10^{-9}$ با وب‌ورکر مرورگر:** استفاده از الگوریتم قطعی ۳۲ بیتی Mulberry32 در هر دو زبان پایتون و تایپ‌اسکریپت برای اجرای بی‌درنگ تعاملی در سایت شخصی.
5. **ایزولاسیون امنیتی کامل (100% Safe Framing):** تمرکز مطلق بر ترافیک شهری، حمل‌ونقل و چراغ‌های راهنمایی؛ حذف هرگونه کلیدواژه با کاربرد دوگانه (نظامی، راداری یا ناوبری خودران).
