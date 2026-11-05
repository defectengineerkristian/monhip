using System.Collections.Generic;

namespace MonhipInstaller
{
	public class LlamaPlan
	{
		public string Tag = "";

		public string Kind = "";

		public string Target = "";

		public List<Asset> Assets = new List<Asset>();

		public long Size;
	}
}
