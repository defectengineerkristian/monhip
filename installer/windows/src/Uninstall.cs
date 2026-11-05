using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;

namespace MonhipInstaller
{
	public static class Uninstall
	{
		public static List<Part> Parts(InstallInfo info)
		{
			string dir = info.Dir;
			List<Part> list = new List<Part>();
			Part part = new Part();
			part.Key = "program";
			part.Label = "Programm";
			Part part2 = part;
			foreach (string item in info.Files.Concat(new string[5] { "app", "Monhip.pyw", "Monhip.exe", "installation.json", "_update" }).Where(ProgramFiles.SafeName).Where(delegate(string n)
			{
				switch (n)
				{
				default:
					return !Const.IsProtected(n);
				case "Monhip.exe":
				case "installation.json":
				case "_update":
					return true;
				}
			})
				.Distinct(StringComparer.OrdinalIgnoreCase))
			{
				part2.Paths.Add(Path.Combine(dir, item));
			}
			list.Add(part2);
			list.Add(Data("chats", "Chats", dir, "chats"));
			list.Add(Data("models", "Modelle (modelle\\)", dir, "modelle"));
			list.Add(Data("server", "llama.cpp / whisper.cpp (server\\)", dir, "server"));
			list.Add(Data("memory", "Gedächtnis und Erinnerungen", dir, "gedaechtnis.json", "erinnerungen.json"));
			list.Add(Data("rooms", "Gruppenchat-Verläufe", dir, "raeume"));
			list.Add(Data("settings", "Einstellungen", dir, "config.json"));
			list.Add(Data("checkpoints", "Rückgängig-Punkte (checkpoints\\)", dir, "checkpoints"));
			list.Add(Data("backups", "Sicherungen", dir, "sicherungen"));
			if (Python.Uninstaller(info) != null)
			{
				list.Add(new Part
				{
					Key = "python",
					Label = "Python " + info.PythonVersion + " (vom Installer)"
				});
			}
			return list.Where((Part p) => p.Key == "program" || p.Key == "python" || p.Paths.Any((string x) => File.Exists(x) || Directory.Exists(x))).ToList();
		}

		private static Part Data(string key, string label, string dir, params string[] names)
		{
			Part part = new Part();
			part.Key = key;
			part.Label = label;
			Part part2 = part;
			foreach (string path in names)
			{
				part2.Paths.Add(Path.Combine(dir, path));
			}
			return part2;
		}

		public static void Measure(List<Part> parts)
		{
			foreach (Part part in parts)
			{
				part.Size = part.Paths.Sum((string x) => Dirs.Size(x));
			}
		}

		public static List<string> Remove(InstallInfo info, List<Part> chosen, Action<string> status)
		{
			string text = Path.GetFullPath(info.Dir).TrimEnd('\\');
			List<string> list = new List<string>();
			foreach (Part item in chosen)
			{
				status(item.Label + " …");
				foreach (string path in item.Paths)
				{
					string fullPath = Path.GetFullPath(path);
					if (string.Equals(Path.GetDirectoryName(fullPath), text, StringComparison.OrdinalIgnoreCase) && !Dirs.Delete(fullPath))
					{
						list.Add(Path.GetFileName(fullPath));
					}
				}
				if (item.Key == "program")
				{
					foreach (string item2 in info.Shortcuts.Where((string x) => x.EndsWith(".lnk", StringComparison.OrdinalIgnoreCase)))
					{
						Dirs.Delete(item2);
					}
					Dirs.Delete(Path.Combine(Path.GetTempPath(), "Monhip"));
					Shell.RemoveAppsEntry();
				}
				if (!(item.Key == "python"))
				{
					continue;
				}
				status("Python " + info.PythonVersion + " …");
				string[] array = Python.Uninstaller(info);
				if (array != null)
				{
					ProcessStartInfo processStartInfo = new ProcessStartInfo(array[0], array[1]);
					processStartInfo.UseShellExecute = false;
					using (Process process = Process.Start(processStartInfo))
					{
						process.WaitForExit();
					}
				}
			}
			List<string> list2 = (Directory.Exists(text) ? Directory.GetFileSystemEntries(text).Select(Path.GetFileName).ToList() : new List<string>());
			if (list2.Count == 0 && Directory.Exists(text))
			{
				try
				{
					Directory.Delete(text, false);
				}
				catch (IOException)
				{
				}
			}
			if (list.Count > 0)
			{
				throw new IOException("Nicht gelöscht (in Verwendung?): " + string.Join(", ", list));
			}
			return list2;
		}
	}
}
