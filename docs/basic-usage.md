# 🔍 Basic Usage

{% hint style="warning" %}
Halcon can make mistakes. Consider checking the information.
{% endhint %}

### 👤 Username Reverse Search

```bash
python halcon.py --username username1
```

```bash
python halcon.py --username username1 username2 username3
```

```bash
python halcon.py --username-file usernames.txt
```

### 📧 Email Reverse Search

```bash
python halcon.py --email email1@email
```

```bash
python halcon.py --email email1@email email2@email email3@email
```

```bash
python halcon.py --email-file emails.txt
```

### 📁 Export

#### PDF

```bash
python halcon.py --username p1ngul1n0 --pdf
```

<figure><img src=".gitbook/assets/pdf-full.png" alt=""><figcaption></figcaption></figure>

#### CSV

```
python halcon.py --username username1 --csv
```

#### JSON

```
python halcon.py --username username1 --json
```

#### DUMP

Dump all found account HTTP responses.

```
python halcon.py --username username1 --dump
```
