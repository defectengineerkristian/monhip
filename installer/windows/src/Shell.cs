using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace MonhipInstaller
{
	public static class Shell
	{
		public static string StartMenu(string name)
		{
			return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), name + ".lnk");
		}

		public static string Desktop(string name)
		{
			return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), name + ".lnk");
		}

		public static void Shortcut(string lnk, string target, string args, string workDir, string description)
		{
			Type typeFromProgID = Type.GetTypeFromProgID("WScript.Shell");
			object obj = Activator.CreateInstance(typeFromProgID);
			try
			{
				object obj2 = typeFromProgID.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, obj, new object[1] { lnk });
				Type type = obj2.GetType();
				type.InvokeMember("TargetPath", BindingFlags.SetProperty, null, obj2, new object[1] { target });
				type.InvokeMember("Arguments", BindingFlags.SetProperty, null, obj2, new object[1] { args });
				type.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, obj2, new object[1] { workDir });
				type.InvokeMember("Description", BindingFlags.SetProperty, null, obj2, new object[1] { description });
				type.InvokeMember("IconLocation", BindingFlags.SetProperty, null, obj2, new object[1] { target + ",0" });
				type.InvokeMember("Save", BindingFlags.InvokeMethod, null, obj2, null);
				Marshal.FinalReleaseComObject(obj2);
			}
			finally
			{
				Marshal.FinalReleaseComObject(obj);
			}
		}

		public static void WriteAppsEntry(InstallInfo info, string key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Monhip")
		{
			using (RegistryKey registryKey = Registry.CurrentUser.CreateSubKey(key))
			{
				registryKey.SetValue("DisplayName", "Monhip");
				registryKey.SetValue("DisplayVersion", info.Label);
				registryKey.SetValue("Publisher", info.Repo.Split('/')[0]);
				registryKey.SetValue("InstallLocation", info.Dir);
				registryKey.SetValue("DisplayIcon", info.Launcher + ",0");
				registryKey.SetValue("UninstallString", Fmt.Quote(info.Launcher) + " --deinstallieren");
				registryKey.SetValue("ModifyPath", Fmt.Quote(info.Launcher) + " --verwalten");
				registryKey.SetValue("URLInfoAbout", "https://github.com/" + info.Repo);
				registryKey.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
				registryKey.SetValue("NoRepair", 1, RegistryValueKind.DWord);
				registryKey.SetValue("EstimatedSize", (int)Math.Min(2147483647L, Dirs.Size(info.Dir) / 1024), RegistryValueKind.DWord);
			}
		}

		public static void UpdateAppsVersion(InstallInfo info)
		{
			try
			{
				using (RegistryKey registryKey = Registry.CurrentUser.OpenSubKey("Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Monhip", true))
				{
					if (registryKey != null)
					{
						registryKey.SetValue("DisplayVersion", info.Label);
					}
				}
			}
			catch (Exception)
			{
			}
		}

		public static void RemoveAppsEntry(string key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Monhip")
		{
			try
			{
				Registry.CurrentUser.DeleteSubKeyTree(key, false);
			}
			catch (Exception)
			{
			}
		}
	}
}
