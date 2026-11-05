using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace MonhipInstaller
{
	public static class Model
	{
		public const string Name = "Qwen3.8-27B";

		public const string Quant = "Q4_K_M";

		public const string HfRepo = "unsloth/Qwen3.8-27B-GGUF";

		public const string Folder = "Qwen3.8-27B";

		public const double NeedGb = 20.0;

		public static readonly string[] Files = new string[2] { "Qwen3.8-27B-UD-Q4_K_M.gguf", "mmproj-F16.gguf" };

		public static string Target(string dir)
		{
			return Path.Combine(dir, "modelle", "Qwen3.8-27B", Files[0]);
		}

		public static List<string> Existing(string dir)
		{
			List<string> list = new List<string>();
			list.Add(Path.Combine(dir, "modelle"));
			List<string> list2 = list;
			List<string> list3 = new List<string>();
			try
			{
				string path = Path.Combine(dir, "config.json");
				if (File.Exists(path))
				{
					object o = Json.Parse(File.ReadAllText(path, Encoding.UTF8));
					list2.AddRange(Json.Strings(o, "folders"));
					list3.AddRange(Json.Strings(o, "extra_models").Where(File.Exists));
				}
			}
			catch (Exception)
			{
			}
			foreach (string item in list2)
			{
				try
				{
					if (Directory.Exists(item))
					{
						list3.AddRange(from x in Directory.EnumerateFiles(item, "*.gguf", SearchOption.AllDirectories)
							where !Path.GetFileName(x).StartsWith("mmproj", StringComparison.OrdinalIgnoreCase)
							select x);
					}
				}
				catch (Exception)
				{
				}
			}
			return list3.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
		}

		public static ModelPlan Plan(string dir)
		{
			ModelPlan modelPlan = new ModelPlan();
			string[] files = Files;
			foreach (string text in files)
			{
				string text2 = Path.Combine(dir, "modelle", "Qwen3.8-27B", text);
				if (!File.Exists(text2))
				{
					string url = "https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/" + text;
					Asset asset = new Asset();
					asset.Name = text;
					asset.Url = url;
					asset.Dest = text2;
					asset.Size = Http.HeadSize(url);
					Asset asset2 = asset;
					modelPlan.Files.Add(asset2);
					modelPlan.Size += asset2.Size;
					if (File.Exists(text2 + ".part"))
					{
						modelPlan.Have += new FileInfo(text2 + ".part").Length;
					}
				}
			}
			return modelPlan;
		}

		public static void Install(ModelPlan p, ProgressFn progress, Cancel cancel)
		{
			long done = 0L;
			foreach (Asset file in p.Files)
			{
				Directory.CreateDirectory(Path.GetDirectoryName(file.Dest));
				string text = file.Dest + ".part";
				done = Http.Download(file.Url, text, done, p.Size, true, progress, cancel);
				if (file.Size > 0 && new FileInfo(text).Length != file.Size)
				{
					throw new Exception(file.Name + " unvollständig.");
				}
				if (File.Exists(file.Dest))
				{
					File.Delete(file.Dest);
				}
				File.Move(text, file.Dest);
			}
		}
	}
}
