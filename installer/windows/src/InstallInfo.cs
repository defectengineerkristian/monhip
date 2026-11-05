using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Microsoft.Win32;

namespace MonhipInstaller
{
	public class InstallInfo
	{
		public string Dir = "";

		public string Repo = "defectengineerkristian/monhip";

		public string Branch = "";

		public string Version = "";

		public string Label = "";

		public string Date = "";

		public string Source = "";

		public string Installed = "";

		public string Python = "";

		public string PythonVersion = "";

		public bool PythonBySetup;

		public bool UpdateCheck = true;

		public List<string> Files = new List<string>();

		public List<string> Shortcuts = new List<string>();

		public string FilePath
		{
			get
			{
				return Path.Combine(Dir, "installation.json");
			}
		}

		public string Launcher
		{
			get
			{
				return Path.Combine(Dir, "Monhip.exe");
			}
		}

		public string Pyw
		{
			get
			{
				return Path.Combine(Dir, "Monhip.pyw");
			}
		}

		public static InstallInfo Load(string dir)
		{
			string path = Path.Combine(dir, "installation.json");
			if (!File.Exists(path))
			{
				return null;
			}
			try
			{
				object o = Json.Parse(File.ReadAllText(path, Encoding.UTF8).TrimStart('\ufeff'));
				InstallInfo installInfo = new InstallInfo();
				installInfo.Dir = Path.GetFullPath(dir);
				installInfo.Repo = Json.Str(o, "repo");
				if (installInfo.Repo == "")
				{
					installInfo.Repo = "defectengineerkristian/monhip";
				}
				installInfo.Branch = Json.Str(o, "branch");
				installInfo.Version = Json.Str(o, "version");
				installInfo.Label = Json.Str(o, "label");
				installInfo.Date = Json.Str(o, "date");
				installInfo.Source = Json.Str(o, "source");
				installInfo.Installed = Json.Str(o, "installed");
				installInfo.Python = Json.Str(o, "python");
				installInfo.PythonVersion = Json.Str(o, "python_version");
				installInfo.PythonBySetup = Json.Str(o, "python_by_setup").ToLowerInvariant() == "true";
				installInfo.UpdateCheck = Json.Str(o, "update_check").ToLowerInvariant() != "false";
				installInfo.Files = Json.Strings(o, "files");
				installInfo.Shortcuts = Json.Strings(o, "shortcuts");
				return installInfo;
			}
			catch (Exception)
			{
				return null;
			}
		}

		public void Save()
		{
			Dictionary<string, object> dictionary = new Dictionary<string, object>();
			dictionary["repo"] = Repo;
			dictionary["branch"] = Branch;
			dictionary["version"] = Version;
			dictionary["label"] = Label;
			dictionary["date"] = Date;
			dictionary["source"] = Source;
			dictionary["installed"] = Installed;
			dictionary["files"] = Files;
			dictionary["python"] = Python;
			dictionary["python_version"] = PythonVersion;
			dictionary["python_by_setup"] = PythonBySetup;
			dictionary["update_check"] = UpdateCheck;
			dictionary["shortcuts"] = Shortcuts;
			string text = FilePath + ".tmp";
			File.WriteAllText(text, Json.Write(dictionary), new UTF8Encoding(false));
			if (File.Exists(FilePath))
			{
				File.Delete(FilePath);
			}
			File.Move(text, FilePath);
		}

		public static InstallInfo FindRegistered()
		{
			try
			{
				using (RegistryKey registryKey = Registry.CurrentUser.OpenSubKey("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Monhip"))
				{
					string text = ((registryKey == null) ? null : (registryKey.GetValue("InstallLocation") as string));
					return string.IsNullOrEmpty(text) ? null : Load(text);
				}
			}
			catch (Exception)
			{
				return null;
			}
		}

		public string Describe()
		{
			string text = Fmt.Date(Date);
			return "Version " + ((Label == "") ? "?" : Label) + ((text != "") ? (" vom " + text) : "");
		}
	}
}
