FROM maven:3.9.9-eclipse-temurin-21 AS blog-build
WORKDIR /build
COPY pom.xml ./
COPY contracts ./contracts
COPY src ./src
RUN cp src/main/resources/application-example.yml src/main/resources/application.yml && mvn -B -DskipTests package

FROM maven:3.9.9-eclipse-temurin-21 AS gateway-build
WORKDIR /build
COPY gateway/pom.xml ./pom.xml
COPY gateway/src ./src
COPY deploy/gateway.yml src/main/resources/application.yml
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-jammy AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* && useradd -u 10001 -m app
WORKDIR /app
USER 10001

FROM runtime AS blog
COPY --from=blog-build /build/target/easyjob-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM runtime AS gateway
COPY --from=gateway-build /build/target/*.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]
