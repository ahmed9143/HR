# HR Enterprise 11.2.0 — Ultimate

هذه النسخة مبنية فوق 11.1.3 Enterprise Flex+ مع طبقة Enterprise UX/Data إضافية.

## تم إصلاح/إضافة فعليًا
- Universal Excel Mapping عربي/إنجليزي مع حفظ أكثر من mapping.
- Leave Balance Import من XLSX/CSV + Paste TSV من Excel + Preview/Commit.
- تعديل رصيد الإجازة مع Leave Balance History.
- QR Identity Center + Generate/Regenerate/Revoke + Bulk + Export ZIP/Excel.
- QR Scan history + USB keyboard-wedge scanner الموجود أصلًا.
- QR تلقائي بجوار الموظف في Employee Directory.
- Employee User provisioning: username تلقائي من الاسم الثنائي أو يدوي + password تلقائي/يدوي + إجبار تغيير أول دخول.
- Employee Profile account card + identity navigation.
- ID Card Designer drag/drop للصورة والاسم والـQR + Front/Back template upload.
- Branding UI: logo + font + login tagline + accent/theme الحاليين.
- Modernized sidebar/navigation visual layer.
- PostgreSQL-compatible network database layer عند توفير `HR_DB_URL` أو `postgres_url.txt`.
- Network launcher يقرأ `postgres_url.txt` بجوار الـEXE.
- إصلاح Network PyInstaller resource path للـfonts/postgresql.
- Network MSI version 11.2.0.
- Compatibility aliases للـLeave import/export والـShift edit/delete.

## الاختبارات
- TEST_FINAL.py — PASS
- TEST_V11_ACCEPTANCE.py — PASS
- TEST_V12_ENTERPRISE.py — PASS
- TEST_FLEX_ACCEPTANCE.py — PASS
- TEST_ID_DESIGNER.py — PASS

## Build
GitHub Actions يبني:
- HR Enterprise.exe
- HR Enterprise Network Server.exe
- HR Enterprise Setup.exe
- HR Enterprise Network Server.msi
