using System;
using System.IO;
using System.Threading;

namespace MonhipInstaller
{
	public static class Dirs
	{
		public static bool IsArm64
		{
			get
			{
				string text = (Environment.GetEnvironmentVariable("PROCESSOR_ARCHITEW6432") ?? Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE") ?? "").ToUpperInvariant();
				return text == "ARM64";
			}
		}

		public static bool Delete(string path)
		{
			for (int i = 0; i < 6; i++)
			{
				try
				{
					if (Directory.Exists(path))
					{
						foreach (string item in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
						{
							File.SetAttributes(item, FileAttributes.Normal);
						}
						Directory.Delete(path, true);
					}
					else if (File.Exists(path))
					{
						File.SetAttributes(path, FileAttributes.Normal);
						File.Delete(path);
					}
					return true;
				}
				catch (IOException)
				{
					Thread.Sleep(700);
				}
				catch (UnauthorizedAccessException)
				{
					Thread.Sleep(700);
				}
			}
			if (!Directory.Exists(path))
			{
				return !File.Exists(path);
			}
			return false;
		}

		public static long Size(string path)
		{
			try
			{
				if (File.Exists(path))
				{
					return new FileInfo(path).Length;
				}
				if (!Directory.Exists(path))
				{
					return 0L;
				}
				long num = 0L;
				foreach (string item in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
				{
					try
					{
						num += new FileInfo(item).Length;
					}
					catch (IOException)
					{
					}
				}
				return num;
			}
			catch (Exception)
			{
				return 0L;
			}
		}

		public static void Move(string from, string to)
		{
			if (Directory.Exists(from))
			{
				Directory.Move(from, to);
			}
			else
			{
				File.Move(from, to);
			}
		}

		public static double FreeGb(string folder)
		{
			try
			{
				string pathRoot = Path.GetPathRoot(Path.GetFullPath(folder));
				return (double)new DriveInfo(pathRoot).AvailableFreeSpace / 1073741824.0;
			}
			catch (Exception)
			{
				return 0.0;
			}
		}
	}
}
