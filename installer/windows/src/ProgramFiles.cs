using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;

namespace MonhipInstaller
{
	public static class ProgramFiles
	{
		public static void Install(InstallInfo info, Latest l, ProgressFn progress, Cancel cancel)
		{
			Directory.CreateDirectory(info.Dir);
			string text = Path.Combine(info.Dir, "_update");
			Dirs.Delete(text);
			Directory.CreateDirectory(Path.Combine(text, "neu"));
			try
			{
				string text2 = Path.Combine(text, "paket.zip");
				Http.Download(l.Zip, text2, 0L, 0L, false, progress, cancel);
				ZipFile.ExtractToDirectory(text2, Path.Combine(text, "neu"));
				string text3 = PackageRoot(Path.Combine(text, "neu"));
				List<string> list = (from n in Directory.EnumerateFileSystemEntries(text3).Select(Path.GetFileName)
					where !Const.IsProtected(n)
					orderby n
					select n).ToList();
				List<string> alt = info.Files.Where((string n) => SafeName(n) && !Const.IsProtected(n)).ToList();
				Swap(info.Dir, text3, list, alt, Path.Combine(text, "alt"));
				info.Files = list;
				info.Version = l.Sha;
				info.Label = l.Label;
				info.Date = l.Date;
				info.Source = l.Source;
				if (l.Branch != "")
				{
					info.Branch = l.Branch;
				}
			}
			finally
			{
				Dirs.Delete(text);
			}
		}

		private static string PackageRoot(string folder)
		{
			string[] fileSystemEntries = Directory.GetFileSystemEntries(folder);
			string text = ((fileSystemEntries.Length == 1 && Directory.Exists(fileSystemEntries[0])) ? fileSystemEntries[0] : folder);
			if (!File.Exists(Path.Combine(text, "Monhip.pyw")) || !File.Exists(Path.Combine(text, "app", "monhip.py")))
			{
				throw new InvalidDataException("Paket unvollständig: Monhip.pyw oder app\\ fehlt.");
			}
			return text;
		}

		public static bool SafeName(string n)
		{
			if (!string.IsNullOrWhiteSpace(n) && n != "." && n != "..")
			{
				return n.IndexOfAny(new char[3] { '\\', '/', ':' }) < 0;
			}
			return false;
		}

		private static void Swap(string dir, string src, List<string> neu, List<string> alt, string backup)
		{
			Directory.CreateDirectory(backup);
			List<string> list = new List<string>();
			List<string> list2 = new List<string>();
			try
			{
				foreach (string item in alt.Concat(neu).Distinct(StringComparer.OrdinalIgnoreCase))
				{
					string text = Path.Combine(dir, item);
					if (Directory.Exists(text) || File.Exists(text))
					{
						Dirs.Move(text, Path.Combine(backup, item));
						list.Add(item);
					}
				}
				foreach (string item2 in neu)
				{
					Dirs.Move(Path.Combine(src, item2), Path.Combine(dir, item2));
					list2.Add(item2);
				}
			}
			catch (Exception)
			{
				foreach (string item3 in list2)
				{
					Dirs.Delete(Path.Combine(dir, item3));
				}
				foreach (string item4 in list)
				{
					Dirs.Move(Path.Combine(backup, item4), Path.Combine(dir, item4));
				}
				throw;
			}
		}
	}
}
