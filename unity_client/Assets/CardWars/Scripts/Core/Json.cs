using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Serialization;

namespace CardWars.Core
{
    /// <summary>
    /// Configuración JSON común: snake_case en el cable (como el servidor Python),
    /// PascalCase en C#. Así los DTO no necesitan un [JsonProperty] por campo.
    /// </summary>
    public static class Json
    {
        public static readonly JsonSerializerSettings Settings = new JsonSerializerSettings
        {
            ContractResolver = new DefaultContractResolver { NamingStrategy = new SnakeCaseNamingStrategy() },
            NullValueHandling = NullValueHandling.Ignore,          // no enviar campos opcionales vacíos
            MissingMemberHandling = MissingMemberHandling.Ignore,  // tolerar campos nuevos del servidor
        };

        public static readonly JsonSerializer Serializer = JsonSerializer.Create(Settings);

        public static string Serialize(object value) => JsonConvert.SerializeObject(value, Settings);

        public static T Deserialize<T>(string json) => JsonConvert.DeserializeObject<T>(json, Settings);

        public static JObject ToJObject(object value) => JObject.FromObject(value, Serializer);

        public static T ToObject<T>(JToken token) => token == null ? default : token.ToObject<T>(Serializer);
    }
}
