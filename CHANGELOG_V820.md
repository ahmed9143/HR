# HR Enterprise V8.2 — Multi-Folder Import + Rollback

## New
- اختيار عدة مجلدات موظفين منفصلة في نفس العملية بدون ZIP.
- إضافة Folder Picker جديد لكل مجلد مع زر إضافة/حذف/مسح.
- الاستمرار في دعم اختيار Employee_Folders كاملًا مرة واحدة.
- دعم ZIP كما هو بدون تغيير.
- كل عملية Folder Import تحصل على Run ID مستقل.
- Import History لمراجعة عمليات استيراد المجلدات.
- Rollback للعملية نفسها فقط، بدون Restore كامل للـDatabase.
- حفظ المستندات السابقة التي تم استبدالها وإعادتها عند Rollback.
- تقرير واضح: matched / review / invalid / imported.

## Safety
- نفس المطابقة الآمنة الموجودة: code → exact name → clear close match.
- المجلد غير الواضح لا يتم ربطه تلقائيًا.
- Transaction واحدة للعملية؛ عند حدوث خطأ يتم rollback للمعاملة.
- حدود حجم الملف وامتدادات المستندات المسموحة مستمرة.

## Compatibility
- ZIP imports remain supported.
- Existing Employee_Folders root wrapper remains supported.
- Existing single-folder browser picker remains supported.
