FROM maven:3.9.9-eclipse-temurin-21 AS blog-build
WORKDIR /build
COPY pom.xml ./
COPY contracts ./contracts
COPY src ./src
COPY auth-common ./auth-common
RUN cp src/main/resources/application-example.yml src/main/resources/application.yml && mvn -B -DskipTests package

FROM maven:3.9.9-eclipse-temurin-21 AS gateway-build
WORKDIR /build/gateway
COPY gateway/pom.xml ./pom.xml
COPY gateway/src ./src
COPY auth-common /build/auth-common
COPY deploy/gateway.yml src/main/resources/application.yml
RUN mvn -B -DskipTests package

FROM maven:3.9.9-eclipse-temurin-21 AS auth-build
WORKDIR /build/auth-service
COPY auth-service/pom.xml ./pom.xml
COPY auth-service/src ./src
COPY auth-common /build/auth-common
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-jammy AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* && useradd -u 10001 -m app
WORKDIR /app
USER 10001

FROM runtime AS blog
COPY --from=blog-build /build/target/easyjob-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM runtime AS gateway
COPY --from=gateway-build /build/gateway/target/*.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM runtime AS auth
COPY --from=auth-build /build/auth-service/target/easyjob-auth-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]

FROM maven:3.9.9-eclipse-temurin-21 AS excel-build
WORKDIR /build/excel-service
COPY excel-service/pom.xml ./pom.xml
COPY excel-service/src ./src
RUN mvn -B -DskipTests package

FROM runtime AS excel
USER root
RUN install -d -o 10001 -g 10001 /app/exports
USER 10001
COPY --from=excel-build /build/excel-service/target/easyjob-excel-0.0.1-SNAPSHOT.jar /app/app.jar
ENTRYPOINT ["java","-jar","/app/app.jar"]
