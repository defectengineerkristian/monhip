using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Management;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace MonhipInstaller
{
	public static class Hw
	{
		[StructLayout(LayoutKind.Sequential)]
		private class MemStatus
		{
			public uint Length = (uint)Marshal.SizeOf(typeof(MemStatus));

			public uint Load;

			public ulong TotalPhys;

			public ulong AvailPhys;

			public ulong TotalPage;

			public ulong AvailPage;

			public ulong TotalVirtual;

			public ulong AvailVirtual;

			public ulong AvailExtended;
		}

		[DllImport("kernel32.dll")]
		private static extern bool GlobalMemoryStatusEx([In][Out] MemStatus m);

		public static string Run(string exe, string args, int timeout)
		{
			try
			{
				ProcessStartInfo processStartInfo = new ProcessStartInfo(exe, args);
				processStartInfo.UseShellExecute = false;
				processStartInfo.RedirectStandardOutput = true;
				processStartInfo.CreateNoWindow = true;
				using (Process process = Process.Start(processStartInfo))
				{
					string result = process.StandardOutput.ReadToEnd();
					process.WaitForExit(timeout);
					return result;
				}
			}
			catch (Exception)
			{
				return "";
			}
		}

		public static Hardware Detect()
		{
			Hardware hardware = new Hardware();
			List<string> list = new List<string>();
			try
			{
				using (ManagementObjectSearcher managementObjectSearcher = new ManagementObjectSearcher("SELECT Name FROM Win32_VideoController"))
				{
					foreach (ManagementObject item in managementObjectSearcher.Get())
					{
						string text = Convert.ToString(item["Name"]);
						if (!string.IsNullOrWhiteSpace(text))
						{
							list.Add(text.Trim());
						}
					}
				}
			}
			catch (Exception)
			{
			}
			string input = Run("nvidia-smi", "", 15000);
			Match match = Regex.Match(input, "CUDA (?:UMD )?Version:\\s*(\\d+)\\.(\\d+)");
			if (match.Success)
			{
				hardware.Cuda = new int[2]
				{
					int.Parse(match.Groups[1].Value),
					int.Parse(match.Groups[2].Value)
				};
			}
			string[][] array = new string[3][]
			{
				new string[2] { "nvidia", "nvidia" },
				new string[3] { "amd", "amd", "radeon" },
				new string[2] { "intel", "intel" }
			};
			string[][] array2 = array;
			foreach (string[] v in array2)
			{
				Func<string, bool> predicate = (string n) => v.Skip(1).Any((string k) => n.ToLowerInvariant().Contains(k));
				string text2 = list.FirstOrDefault(predicate);
				if (text2 != null)
				{
					hardware.Vendor = v[0];
					hardware.Gpu = text2;
					break;
				}
			}
			if (hardware.Vendor == "" && list.Count > 0)
			{
				hardware.Gpu = list[0];
			}
			List<long> list2 = (from Match x in Regex.Matches(Run("nvidia-smi", "--query-gpu=memory.total --format=csv,noheader,nounits", 15000), "\\d+")
				select long.Parse(x.Value)).ToList();
			hardware.VramGb = ((list2.Count > 0) ? ((double)list2.Max() / 1024.0) : ((double)RegistryVram() / 1073741824.0));
			MemStatus memStatus = new MemStatus();
			if (GlobalMemoryStatusEx(memStatus))
			{
				hardware.RamGb = (double)memStatus.TotalPhys / 1073741824.0;
			}
			return hardware;
		}

		private static long RegistryVram()
		{
			long num = 0L;
			try
			{
				using (RegistryKey registryKey = Registry.LocalMachine.OpenSubKey("SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}"))
				{
					if (registryKey == null)
					{
						return 0L;
					}
					string[] subKeyNames = registryKey.GetSubKeyNames();
					foreach (string name in subKeyNames)
					{
						try
						{
							using (RegistryKey registryKey2 = registryKey.OpenSubKey(name))
							{
								object obj = ((registryKey2 == null) ? null : registryKey2.GetValue("HardwareInformation.qwMemorySize"));
								long val = ((obj is byte[] && ((byte[])obj).Length >= 8) ? BitConverter.ToInt64((byte[])obj, 0) : ((obj != null) ? Convert.ToInt64(obj) : 0));
								num = Math.Max(num, val);
							}
						}
						catch (Exception)
						{
						}
					}
				}
			}
			catch (Exception)
			{
			}
			return num;
		}
	}
}
