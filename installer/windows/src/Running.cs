using System;
using System.Collections.Generic;
using System.Management;

namespace MonhipInstaller
{
	public static class Running
	{
		public static List<int> InDir(string dir)
		{
			List<int> list = new List<int>();
			try
			{
				string queryString = "SELECT ProcessId, CommandLine, ExecutablePath FROM Win32_Process WHERE Name LIKE 'python%' OR Name = 'llama-server.exe' OR Name = 'whisper-cli.exe'";
				using (ManagementObjectSearcher managementObjectSearcher = new ManagementObjectSearcher(queryString))
				{
					foreach (ManagementObject item in managementObjectSearcher.Get())
					{
						string text = Convert.ToString(item["CommandLine"]) + " " + Convert.ToString(item["ExecutablePath"]);
						if (text.IndexOf(dir, StringComparison.OrdinalIgnoreCase) >= 0)
						{
							list.Add(Convert.ToInt32(item["ProcessId"]));
						}
					}
				}
			}
			catch (Exception)
			{
			}
			return list;
		}
	}
}
