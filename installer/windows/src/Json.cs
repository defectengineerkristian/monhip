using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Web.Script.Serialization;

namespace MonhipInstaller
{
	public static class Json
	{
		private static JavaScriptSerializer Make()
		{
			JavaScriptSerializer javaScriptSerializer = new JavaScriptSerializer();
			javaScriptSerializer.MaxJsonLength = int.MaxValue;
			javaScriptSerializer.RecursionLimit = 256;
			return javaScriptSerializer;
		}

		public static object Parse(string text)
		{
			return Make().DeserializeObject(text);
		}

		public static string Write(object o)
		{
			return Make().Serialize(o);
		}

		public static Dictionary<string, object> Obj(object o)
		{
			return o as Dictionary<string, object>;
		}

		public static object Get(object o, string key)
		{
			Dictionary<string, object> dictionary = Obj(o);
			object value;
			if (dictionary == null || !dictionary.TryGetValue(key, out value))
			{
				return null;
			}
			return value;
		}

		public static string Str(object o, string key)
		{
			object obj = Get(o, key);
			if (obj != null)
			{
				return Convert.ToString(obj, CultureInfo.InvariantCulture);
			}
			return "";
		}

		public static object[] Arr(object o, string key)
		{
			object[] array = Get(o, key) as object[];
			if (array != null)
			{
				return array;
			}
			ArrayList arrayList = Get(o, key) as ArrayList;
			if (arrayList == null)
			{
				return new object[0];
			}
			return arrayList.ToArray();
		}

		public static List<string> Strings(object o, string key)
		{
			object obj = Get(o, key);
			if (obj is string)
			{
				List<string> list = new List<string>();
				list.Add((string)obj);
				return list;
			}
			return (from x in Arr(o, key)
				select Convert.ToString(x, CultureInfo.InvariantCulture)).ToList();
		}

		public static long Long(object o, string key)
		{
			object obj = Get(o, key);
			long result;
			if (obj == null || !long.TryParse(Convert.ToString(obj, CultureInfo.InvariantCulture), out result))
			{
				return 0L;
			}
			return result;
		}
	}
}
