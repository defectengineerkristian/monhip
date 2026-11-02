using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text.RegularExpressions;

namespace MonhipInstaller
{
	public static class Llama
	{
		private static readonly Regex Folder = new Regex("^llama-b(\\d+)-bin-win-(.+)-(?:x64|arm64)$");

		public static string ServerDir(string dir)
		{
			return Path.Combine(dir, "server");
		}

		public static List<string> Installed(string dir)
		{
			string path = ServerDir(dir);
			if (!Directory.Exists(path))
			{
				return new List<string>();
			}
			return (from n in (from d in Directory.GetDirectories(path)
					where File.Exists(Path.Combine(d, "llama-server.exe")) && !d.EndsWith(".part") && !d.EndsWith(".alt")
					select d).Select(Path.GetFileName)
				orderby n descending
				select n).ToList();
		}

		public static string Label(string folder)
		{
			Match match = Folder.Match(folder);
			if (!match.Success)
			{
				return folder;
			}
			return "b" + match.Groups[1].Value + " · " + KindLabel(match.Groups[2].Value);
		}

		private static string KindLabel(string kind)
		{
			int num = kind.IndexOf('-');
			string text = ((num < 0) ? kind : kind.Substring(0, num));
			string text2 = ((num < 0) ? "" : kind.Substring(num + 1));
			Dictionary<string, string> dictionary = new Dictionary<string, string>();
			dictionary.Add("cuda", "CUDA");
			dictionary.Add("rocm", "ROCm");
			dictionary.Add("vulkan", "Vulkan");
			dictionary.Add("cpu", "CPU");
			dictionary.Add("sycl", "SYCL");
			Dictionary<string, string> dictionary2 = dictionary;
			if (dictionary2.ContainsKey(text))
			{
				text = dictionary2[text];
			}
			if (!(text2 == ""))
			{
				return text + " " + text2;
			}
			return text;
		}

		public static LlamaPlan Plan(string dir, Hardware hw)
		{
			string text = (Dirs.IsArm64 ? "arm64" : "x64");
			object[] array = Http.GetJson("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10", 30000) as object[];
			object[] array2 = array ?? new object[0];
			foreach (object o in array2)
			{
				if (Json.Str(o, "draft").ToLowerInvariant() == "true")
				{
					continue;
				}
				string text2 = Json.Str(o, "tag_name");
				if (!Regex.IsMatch(text2, "^b\\d+$"))
				{
					continue;
				}
				Dictionary<string, object> dictionary = new Dictionary<string, object>();
				object[] array3 = Json.Arr(o, "assets");
				foreach (object obj in array3)
				{
					dictionary[Json.Str(obj, "name")] = obj;
				}
				LlamaPlan llamaPlan = new LlamaPlan();
				llamaPlan.Tag = text2;
				LlamaPlan llamaPlan2 = llamaPlan;
				List<object> list = new List<object>();
				if (hw.Vendor == "nvidia")
				{
					Regex pat = new Regex("^llama-" + Regex.Escape(text2) + "-bin-win-cuda-(\\d+)\\.(\\d+)-" + text + "\\.zip$");
					List<int[]> source = (from n in dictionary.Keys
						select pat.Match(n) into x
						where x.Success
						select new int[2]
						{
							int.Parse(x.Groups[1].Value),
							int.Parse(x.Groups[2].Value)
						} into v
						orderby v[0] * 1000 + v[1]
						select v).ToList();
					List<int[]> list2 = ((hw.Cuda != null) ? source.Where((int[] v) => v[0] * 1000 + v[1] <= hw.Cuda[0] * 1000 + hw.Cuda[1]).ToList() : source.Take(1).ToList());
					if (list2.Count > 0)
					{
						string text3 = list2.Last()[0] + "." + list2.Last()[1];
						list.Add(dictionary["llama-" + text2 + "-bin-win-cuda-" + text3 + "-" + text + ".zip"]);
						object value;
						if (dictionary.TryGetValue("cudart-llama-bin-win-cuda-" + text3 + "-" + text + ".zip", out value))
						{
							list.Add(value);
						}
						llamaPlan2.Kind = "CUDA " + text3;
					}
				}
				object value2;
				if (list.Count == 0 && hw.Vendor != "" && dictionary.TryGetValue("llama-" + text2 + "-bin-win-vulkan-" + text + ".zip", out value2))
				{
					list.Add(value2);
					llamaPlan2.Kind = "Vulkan";
				}
				if (list.Count == 0 && dictionary.TryGetValue("llama-" + text2 + "-bin-win-cpu-" + text + ".zip", out value2))
				{
					list.Add(value2);
					llamaPlan2.Kind = "CPU";
				}
				if (list.Count == 0)
				{
					continue;
				}
				foreach (object item in list)
				{
					llamaPlan2.Assets.Add(new Asset
					{
						Name = Json.Str(item, "name"),
						Url = Json.Str(item, "browser_download_url"),
						Size = Json.Long(item, "size")
					});
				}
				llamaPlan2.Size = llamaPlan2.Assets.Sum((Asset a) => a.Size);
				llamaPlan2.Target = Path.Combine(ServerDir(dir), Path.GetFileNameWithoutExtension(llamaPlan2.Assets[0].Name));
				return llamaPlan2;
			}
			throw new Exception("Keine passende llama.cpp-Version für Windows gefunden.");
		}

		public static void Install(LlamaPlan p, ProgressFn progress, Cancel cancel)
		{
			string text = p.Target + ".part";
			Directory.CreateDirectory(Path.GetDirectoryName(p.Target));
			Dirs.Delete(text);
			Directory.CreateDirectory(text);
			try
			{
				long done = 0L;
				foreach (Asset asset in p.Assets)
				{
					string text2 = Path.Combine(text, asset.Name);
					done = Http.Download(asset.Url, text2, done, p.Size, false, progress, cancel);
					using (ZipArchive zipArchive = ZipFile.OpenRead(text2))
					{
						foreach (ZipArchiveEntry entry in zipArchive.Entries)
						{
							string fullPath = Path.GetFullPath(Path.Combine(text, entry.FullName));
							if (fullPath.StartsWith(text + Path.DirectorySeparatorChar))
							{
								if (entry.Name == "")
								{
									Directory.CreateDirectory(fullPath);
									continue;
								}
								Directory.CreateDirectory(Path.GetDirectoryName(fullPath));
								entry.ExtractToFile(fullPath, true);
							}
						}
					}
					File.Delete(text2);
				}
				string[] directories = Directory.GetDirectories(text);
				if (!File.Exists(Path.Combine(text, "llama-server.exe")) && directories.Length == 1 && File.Exists(Path.Combine(directories[0], "llama-server.exe")))
				{
					string[] fileSystemEntries = Directory.GetFileSystemEntries(directories[0]);
					foreach (string text3 in fileSystemEntries)
					{
						Dirs.Move(text3, Path.Combine(text, Path.GetFileName(text3)));
					}
					Directory.Delete(directories[0]);
				}
				if (!File.Exists(Path.Combine(text, "llama-server.exe")))
				{
					throw new Exception("llama-server.exe fehlt im Paket.");
				}
				Dirs.Delete(p.Target);
				Directory.Move(text, p.Target);
			}
			catch (Exception)
			{
				Dirs.Delete(text);
				throw;
			}
			RemoveOlder(p.Target);
		}

		private static void RemoveOlder(string target)
		{
			Match match = Folder.Match(Path.GetFileName(target));
			if (!match.Success)
			{
				return;
			}
			string text = match.Groups[2].Value.Split('-')[0];
			string[] directories = Directory.GetDirectories(Path.GetDirectoryName(target));
			foreach (string text2 in directories)
			{
				Match match2 = Folder.Match(Path.GetFileName(text2));
				if (!(text2 == target) && match2.Success && !(match2.Groups[2].Value.Split('-')[0] != text))
				{
					try
					{
						Directory.Move(text2, text2 + ".alt");
						Dirs.Delete(text2 + ".alt");
					}
					catch (IOException)
					{
					}
				}
			}
		}
	}
}
