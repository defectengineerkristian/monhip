using System.Collections.Generic;

namespace MonhipInstaller
{
	public class Part
	{
		public string Key;

		public string Label;

		public List<string> Paths = new List<string>();

		public long Size;

		public bool Enabled = true;
	}
}
