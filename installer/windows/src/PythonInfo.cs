using System;
using System.IO;

namespace MonhipInstaller
{
	public class PythonInfo
	{
		public Version Version;

		public string Exe;

		public string Pythonw
		{
			get
			{
				string text = Path.Combine(Path.GetDirectoryName(Exe), "pythonw.exe");
				if (!File.Exists(text))
				{
					return Exe;
				}
				return text;
			}
		}
	}
}
