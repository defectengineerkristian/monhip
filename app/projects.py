"""Vorlagen für neue Programmierprojekte (create_project im Agenten-Modus).

Neue Sprache: Eintrag in TEMPLATES (Dateien mit Platzhaltern __NAME__, __IDENT__, __PKG__, __CLASS__)
und ggf. Kurznamen in ALIASES ergänzen.
"""

import re

GITIGNORE_COMMON = ".vscode/\n.idea/\n*.log\n.DS_Store\nThumbs.db\n"

TEMPLATES = {
    "python": {
        "label": "Python",
        "tools": ["py", "python"],
        "run": "py main.py",
        "files": {
            "main.py": '"""__NAME__"""\n\n\ndef main():\n    print("Hallo aus __NAME__!")\n\n\n'
                       'if __name__ == "__main__":\n    main()\n',
            "requirements.txt": "",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\nvenv/\n" + GITIGNORE_COMMON,
        },
    },
    "java": {
        "label": "Java (Maven)",
        "tools": ["java", "javac", "mvn"],
        "run": "mvn -q compile exec:java   (ohne Maven: javac -d out src/main/java/__PKG__/Main.java; "
               "java -cp out __PKG__.Main)",
        "files": {
            "pom.xml": """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>__PKG__</groupId>
    <artifactId>__IDENT__</artifactId>
    <version>1.0.0</version>
    <properties>
        <maven.compiler.release>17</maven.compiler.release>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <exec.mainClass>__PKG__.Main</exec.mainClass>
    </properties>
</project>
""",
            "src/main/java/__PKG__/Main.java": "package __PKG__;\n\npublic class Main {\n"
                                               "    public static void main(String[] args) {\n"
                                               '        System.out.println("Hallo aus __NAME__!");\n    }\n}\n',
            ".gitignore": "target/\nout/\n*.class\n" + GITIGNORE_COMMON,
        },
    },
    "cpp": {
        "label": "C++ (CMake)",
        "tools": ["cmake", "g++", "clang++", "cl"],
        "run": "cmake -S . -B build && cmake --build build   (ohne CMake: g++ -std=c++20 -O2 -o __IDENT__ src/main.cpp)",
        "files": {
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.16)\nproject(__IDENT__ LANGUAGES CXX)\n\n"
                              "set(CMAKE_CXX_STANDARD 20)\nset(CMAKE_CXX_STANDARD_REQUIRED ON)\n\n"
                              "add_executable(__IDENT__ src/main.cpp)\n",
            "src/main.cpp": '#include <iostream>\n\nint main() {\n    std::cout << "Hallo aus __NAME__!" << std::endl;\n'
                            "    return 0;\n}\n",
            ".gitignore": "build/\n*.exe\n*.o\n*.obj\n" + GITIGNORE_COMMON,
        },
    },
    "c": {
        "label": "C (CMake)",
        "tools": ["cmake", "gcc", "clang", "cl"],
        "run": "cmake -S . -B build && cmake --build build   (ohne CMake: gcc -O2 -o __IDENT__ src/main.c)",
        "files": {
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.16)\nproject(__IDENT__ LANGUAGES C)\n\n"
                              "set(CMAKE_C_STANDARD 17)\n\nadd_executable(__IDENT__ src/main.c)\n",
            "src/main.c": '#include <stdio.h>\n\nint main(void) {\n    printf("Hallo aus __NAME__!\\n");\n    return 0;\n}\n',
            ".gitignore": "build/\n*.exe\n*.o\n*.obj\n" + GITIGNORE_COMMON,
        },
    },
    "rust": {
        "label": "Rust (Cargo)",
        "tools": ["cargo", "rustc"],
        "run": "cargo run",
        "files": {
            "Cargo.toml": '[package]\nname = "__IDENT__"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n',
            "src/main.rs": 'fn main() {\n    println!("Hallo aus __NAME__!");\n}\n',
            ".gitignore": "/target\n" + GITIGNORE_COMMON,
        },
    },
    "csharp": {
        "label": "C# (.NET)",
        "tools": ["dotnet"],
        "run": "dotnet run",
        "files": {
            "__CLASS__.csproj": '<Project Sdk="Microsoft.NET.Sdk">\n\n  <PropertyGroup>\n    <OutputType>Exe</OutputType>\n'
                                "    <TargetFramework>net8.0</TargetFramework>\n    <ImplicitUsings>enable</ImplicitUsings>\n"
                                "    <Nullable>enable</Nullable>\n    <RootNamespace>__CLASS__</RootNamespace>\n"
                                "  </PropertyGroup>\n\n</Project>\n",
            "Program.cs": 'namespace __CLASS__;\n\ninternal static class Program\n{\n    private static void Main(string[] args)\n'
                          '    {\n        Console.WriteLine("Hallo aus __NAME__!");\n    }\n}\n',
            ".gitignore": "bin/\nobj/\n" + GITIGNORE_COMMON,
        },
    },
    "node": {
        "label": "JavaScript (Node.js)",
        "tools": ["node", "npm"],
        "run": "node index.js   (Pakete: npm install <paket>)",
        "files": {
            "package.json": '{\n  "name": "__IDENT_DASH__",\n  "version": "1.0.0",\n  "description": "__NAME__",\n'
                            '  "main": "index.js",\n  "type": "module",\n  "scripts": {\n    "start": "node index.js"\n  }\n}\n',
            "index.js": 'console.log("Hallo aus __NAME__!");\n',
            ".gitignore": "node_modules/\n" + GITIGNORE_COMMON,
        },
    },
    "web": {
        "label": "Webseite (HTML/CSS/JS)",
        "tools": [],
        "run": "index.html im Browser öffnen (open_path)",
        "files": {
            "index.html": '<!DOCTYPE html>\n<html lang="de">\n<head>\n  <meta charset="UTF-8">\n'
                          '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                          "  <title>__NAME__</title>\n  <link rel=\"stylesheet\" href=\"style.css\">\n</head>\n<body>\n"
                          "  <main>\n    <h1>__NAME__</h1>\n    <p id=\"info\">Hallo!</p>\n  </main>\n"
                          '  <script src="script.js"></script>\n</body>\n</html>\n',
            "style.css": "* { box-sizing: border-box; }\n\nbody {\n  margin: 0;\n  font-family: system-ui, sans-serif;\n"
                         "  line-height: 1.6;\n  color: #1f2937;\n  background: #f9fafb;\n}\n\n"
                         "main {\n  max-width: 800px;\n  margin: 0 auto;\n  padding: 2rem 1rem;\n}\n",
            "script.js": 'document.getElementById("info").textContent = "JavaScript läuft.";\n',
        },
    },
    "go": {
        "label": "Go",
        "tools": ["go"],
        "run": "go run .",
        "files": {
            "go.mod": "module __IDENT__\n\ngo 1.22\n",
            "main.go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hallo aus __NAME__!")\n}\n',
            ".gitignore": "*.exe\n" + GITIGNORE_COMMON,
        },
    },
}

ALIASES = {
    "py": "python", "python3": "python", "java": "java", "maven": "java", "c++": "cpp", "cxx": "cpp",
    "cplusplus": "cpp", "c#": "csharp", "cs": "csharp", ".net": "csharp", "dotnet": "csharp", "js": "node",
    "javascript": "node", "nodejs": "node", "node.js": "node", "html": "web", "website": "web", "webseite": "web",
    "golang": "go", "rs": "rust",
}


def languages() -> str:
    return ", ".join(TEMPLATES)


def resolve(language: str) -> str | None:
    key = language.strip().lower()
    key = ALIASES.get(key, key)
    return key if key in TEMPLATES else None


def folder_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    return re.sub(r"\s+", "-", name) or "projekt"


def _placeholders(name: str) -> dict[str, str]:
    words = re.findall(r"[A-Za-z0-9]+", name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                       .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue").replace("ß", "ss")) or ["projekt"]
    ident = "_".join(w.lower() for w in words)
    if ident[0].isdigit():
        ident = "p_" + ident
    cls = "".join(w[:1].upper() + w[1:] for w in words)
    return {
        "__NAME__": name.replace('"', "'"),
        "__IDENT_DASH__": ident.replace("_", "-"),
        "__IDENT__": ident,
        "__PKG__": ident.replace("_", ""),
        "__CLASS__": cls if not cls[0].isdigit() else "P" + cls,
    }


def _fill(s: str, repl: dict) -> str:
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def files_for(language: str, name: str) -> dict[str, str]:
    """Dateien (relativer Pfad → Inhalt) für ein neues Projekt."""
    tpl, repl = TEMPLATES[language], _placeholders(name)
    files = {_fill(path, repl): _fill(content, repl) for path, content in tpl["files"].items()}
    files["README.md"] = (f"# {name}\n\n{tpl['label']}-Projekt, angelegt mit Monhip.\n\n"
                          f"## Starten\n\n```\n{run_hint(language, name)}\n```\n")
    return files


def run_hint(language: str, name: str) -> str:
    return _fill(TEMPLATES[language]["run"], _placeholders(name))
