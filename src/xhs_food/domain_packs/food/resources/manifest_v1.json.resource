{
  "manifestVersion": "domain-pack-manifest/v1",
  "domainId": "food",
  "packVersion": "1.0.0",
  "contractApi": "domain-contract/v1",
  "coreVersionRange": ">=1.0.0,<2.0.0",
  "manifestDigest": "9d46b1d28b4093854faf7a0d4d912cfa54438ce938de9239f803f6d786de17d3",
  "methods": [
    "describe",
    "classify_constraints",
    "validate_evidence",
    "compute_features",
    "score_public",
    "build_final_output",
    "map_error"
  ],
  "domainSchemas": {
    "entities": "urn:food-agent:food:entities:v1",
    "relations": "urn:food-agent:food:relations:v1",
    "evidenceTypes": "urn:food-agent:food:evidence-types:v1",
    "featureSet": "urn:food-agent:food:feature-set:v1",
    "personalizationSlots": "urn:food-agent:food:personalization-slots:v1"
  },
  "methodSchemas": [
    {
      "method": "describe",
      "inputSchemaId": "urn:food-agent:domain-method:describe-input:v1",
      "inputSchemaDigest": "c67a3ef58bea90053d76251c9f9b7d72513a473ac3b493a776f871b694ebdc4c",
      "outputSchemaId": "urn:food-agent:domain-pack-manifest:v1",
      "outputSchemaDigest": "cf18f7372cdf8cc103748c7a39e72258810a910db4a70783b7facf52335eb29c"
    },
    {
      "method": "classify_constraints",
      "inputSchemaId": "urn:food-agent:domain-method:classify-constraints-input:v1",
      "inputSchemaDigest": "019cdb9754bdbf064e03cf206d7584f3269b3e59e3b627ee84e661cbcaaae0a9",
      "outputSchemaId": "urn:food-agent:domain-method:classify-constraints-output:v1",
      "outputSchemaDigest": "483114a40fb6d8469fa36edabab3de30c1afe5a9f99365f43e4cdcfeea48a75e"
    },
    {
      "method": "validate_evidence",
      "inputSchemaId": "urn:food-agent:domain-method:validate-evidence-input:v1",
      "inputSchemaDigest": "282060148fe54aff339d706de15f6296db479a051450a6700c53666808e793f2",
      "outputSchemaId": "urn:food-agent:domain-method:validate-evidence-output:v1",
      "outputSchemaDigest": "651bb0bda11b0b60bbba677b7ed8a5267f81883ad781b80074d00806a49590e4"
    },
    {
      "method": "compute_features",
      "inputSchemaId": "urn:food-agent:domain-method:compute-features-input:v1",
      "inputSchemaDigest": "7eef327d351a18492f10c0f04352f059de7d4b4ee877954a8d810023f15598c9",
      "outputSchemaId": "urn:food-agent:domain-method:compute-features-output:v1",
      "outputSchemaDigest": "1c54963e6e3b7ab68227c85316ebac54562cac12858f1c5cb5f342ee0b382f86"
    },
    {
      "method": "score_public",
      "inputSchemaId": "urn:food-agent:domain-method:score-public-input:v1",
      "inputSchemaDigest": "b693f9a6beb436169d5dc5bb909a36a09bd4d3417b9db1baa73318e0b273c4fc",
      "outputSchemaId": "urn:food-agent:domain-method:score-public-output:v1",
      "outputSchemaDigest": "ca3e9da31b4c2dcbcc22f50a55fd638c1fc6ab0c51935aa8f01c566e9746c664"
    },
    {
      "method": "build_final_output",
      "inputSchemaId": "urn:food-agent:domain-method:build-final-output-input:v1",
      "inputSchemaDigest": "6af85cf0fe2403472b0e134dafcedb00784568be90db7fc08e6d4fb5e57e7737",
      "outputSchemaId": "urn:food-agent:domain-method:build-final-output-output:v1",
      "outputSchemaDigest": "9c034f3eff03c535891876717eaa18e8cb91c4341720d3bb482d987bb461e78e"
    },
    {
      "method": "map_error",
      "inputSchemaId": "urn:food-agent:domain-method:map-error-input:v1",
      "inputSchemaDigest": "01ae2d7e4ec811204bf099839eb4e9f670981e7892e9a2bff3a5948474d8a674",
      "outputSchemaId": "urn:food-agent:stable-error:v1",
      "outputSchemaDigest": "d5f01b2f63a02aba36561c5a9248ca65f60c6cb73fcbc7deff6acb8c4fad6e51"
    }
  ],
  "allowedTools": [
    {
      "toolId": "place.lookup",
      "toolVersion": "1.0.0",
      "permission": "source.place.read",
      "timeoutMs": 3000,
      "errorCodes": [
        "dependency_unavailable",
        "rate_limited",
        "invalid_tool_result"
      ],
      "inputSchemaDigest": "51c1c7fc88f092f5db4f63d5a067ab41abdf38749ad612e5c5f2733508b14054",
      "outputSchemaDigest": "96d0b288e655c18e18fe8717e3908f66105deedeea11aa9755de253c12568395",
      "inputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:food-agent:tool:place.lookup:input:v1",
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "query",
          "geo"
        ],
        "properties": {
          "schemaVersion": {
            "const": "place.lookup/input/v1"
          },
          "query": {
            "type": "string",
            "minLength": 1
          },
          "geo": {
            "type": "string",
            "minLength": 1
          }
        }
      },
      "inputExample": {
        "schemaVersion": "place.lookup/input/v1",
        "query": "老灶火锅",
        "geo": "CN-SC-Zigong"
      },
      "outputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:food-agent:tool:place.lookup:output:v1",
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "places"
        ],
        "properties": {
          "schemaVersion": {
            "const": "place.lookup/output/v1"
          },
          "places": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "sourceId",
                "name",
                "address"
              ],
              "properties": {
                "sourceId": {
                  "type": "string",
                  "minLength": 1
                },
                "name": {
                  "type": "string",
                  "minLength": 1
                },
                "address": {
                  "type": "string"
                }
              }
            }
          }
        }
      },
      "outputExample": {
        "schemaVersion": "place.lookup/output/v1",
        "places": [
          {
            "sourceId": "poi-001",
            "name": "老灶火锅",
            "address": "自流井区"
          }
        ]
      }
    },
    {
      "toolId": "evidence.search_reviews",
      "toolVersion": "1.0.0",
      "permission": "source.reviews.read",
      "timeoutMs": 5000,
      "errorCodes": [
        "dependency_unavailable",
        "rate_limited",
        "invalid_tool_result"
      ],
      "inputSchemaDigest": "a9caa8c7df484c1785e2784b2d4f55d658e4052ea080aaae6f6a586ff18545c1",
      "outputSchemaDigest": "0729adab6def2d9e72d7e8456d279664c2edbffd4d433679b51f80acc2c16546",
      "inputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:food-agent:tool:evidence.search-reviews:input:v1",
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "keywords",
          "limit"
        ],
        "properties": {
          "schemaVersion": {
            "const": "evidence.search-reviews/input/v1"
          },
          "keywords": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "string",
              "minLength": 1
            }
          },
          "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100
          }
        }
      },
      "inputExample": {
        "schemaVersion": "evidence.search-reviews/input/v1",
        "keywords": [
          "自贡",
          "本地火锅"
        ],
        "limit": 20
      },
      "outputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:food-agent:tool:evidence.search-reviews:output:v1",
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "batchRef",
          "itemCount"
        ],
        "properties": {
          "schemaVersion": {
            "const": "evidence.search-reviews/output/v1"
          },
          "batchRef": {
            "type": "string",
            "minLength": 1
          },
          "itemCount": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "outputExample": {
        "schemaVersion": "evidence.search-reviews/output/v1",
        "batchRef": "canonical-source-batch/01J0FOOD",
        "itemCount": 12
      }
    }
  ],
  "finalOutputSchemaDigest": "2b5334db461f1c7b6dc831f94a4fc85bb228c471a14f83f3038d4fd2de1fb2c7",
  "finalOutputSchema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:food-agent:food:agent-final-output:v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "summary",
      "recommendations"
    ],
    "properties": {
      "schemaVersion": {
        "const": "food-agent-final-output/v1"
      },
      "summary": {
        "type": "string"
      },
      "recommendations": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "entityId",
            "publicScore",
            "explanationRefs"
          ],
          "properties": {
            "entityId": {
              "type": "string",
              "minLength": 1
            },
            "publicScore": {
              "type": "number",
              "minimum": 0,
              "maximum": 1
            },
            "explanationRefs": {
              "type": "array",
              "items": {
                "type": "string"
              }
            }
          }
        }
      }
    }
  },
  "finalOutputExample": {
    "schemaVersion": "food-agent-final-output/v1",
    "summary": "找到 1 个公共候选。",
    "recommendations": [
      {
        "entityId": "restaurant-001",
        "publicScore": 0.91,
        "explanationRefs": [
          "evidence-001"
        ]
      }
    ]
  },
  "scoringPolicy": {
    "policyId": "food.public-score",
    "policyVersion": "1.0.0",
    "mode": "pure_deterministic",
    "inputs": [
      "declared_public_feature_set",
      "explicit_versioned_config"
    ],
    "forbiddenInputs": [
      "user_memory",
      "session_memory",
      "wall_clock",
      "randomness",
      "environment",
      "framework_state"
    ],
    "forbiddenEffects": [
      "network",
      "filesystem",
      "database",
      "cache",
      "workflow",
      "connector"
    ]
  },
  "domainSources": [
    {
      "capability": "place.lookup",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": true
    },
    {
      "capability": "reviews.search",
      "versionRange": ">=1.0.0,<2.0.0",
      "required": true
    }
  ],
  "policyProfiles": {
    "workflow": "research-standard/v1",
    "freshness": "food-freshness/v1",
    "coverage": "food-coverage/v1",
    "stopping": "food-stopping/v1",
    "refreshJob": "food-refresh-declaration/v1"
  }
}

